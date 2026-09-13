import json
import logging
import os

import anthropic

from ai_classifier import MODEL, _extract_json
from models import Technician, Ticket

logger = logging.getLogger(__name__)

# Below this many completed+rated tickets in the ticket's own category, a
# candidate's category rating is considered too thin to trust, and we widen
# the stats to that technician's record across all categories instead.
MIN_CATEGORY_SAMPLES = 2

SYSTEM_PROMPT = """You are a dispatcher assistant choosing the best technician for a maintenance ticket.

You will receive the ticket details and a list of candidate technicians who
already match the required category and are available. Each candidate has a
resume summary, an average customer rating, and a count of completed jobs.

Pick the single best candidate based on how well their resume/experience
fits the specific issue described, weighed against their rating history. A
technician with little or no rating history is not automatically worse -
use judgment, but prefer proven, well-rated technicians when the fit
between candidates is otherwise close.

Respond with STRICT JSON only. No markdown, no code fences, no explanation
before or after the JSON. Respond with exactly one JSON object of this
shape:

{"technician_id": <int>, "reasoning": "one short sentence"}

Rules:
- "technician_id" must be exactly one of the candidate IDs provided.
- "reasoning" is a single short sentence explaining the choice, written in
  the same language as the ticket description.
"""


def _technician_stats(technician_id, category):
    """Average client_rating and completed-ticket count for a technician.

    Prefers stats scoped to `category`; falls back to the technician's
    record across all categories when the category sample is too thin
    (see MIN_CATEGORY_SAMPLES).
    """

    def _completed(scoped_to_category):
        query = Ticket.query.filter(
            Ticket.assigned_to == technician_id, Ticket.status == "completed"
        )
        if scoped_to_category:
            query = query.filter(Ticket.category == category)
        return query.all()

    category_tickets = _completed(scoped_to_category=True)
    if len(category_tickets) >= MIN_CATEGORY_SAMPLES:
        tickets, based_on = category_tickets, "category"
    else:
        tickets, based_on = _completed(scoped_to_category=False), "overall"

    ratings = [t.client_rating for t in tickets if t.client_rating is not None]
    avg_rating = sum(ratings) / len(ratings) if ratings else None

    return {"avg_rating": avg_rating, "completed_count": len(tickets), "based_on": based_on}


def _pick_best_by_rating(candidates, stats_by_id):
    def sort_key(technician):
        stats = stats_by_id[technician.id]
        avg = stats["avg_rating"]
        return (avg is None, -(avg or 0.0), -stats["completed_count"], technician.id)

    return sorted(candidates, key=sort_key)[0]


def _format_candidate(candidate, stats):
    resume = candidate.resume_summary or "Резюме-саммарі відсутнє."
    if stats["avg_rating"] is None:
        rating = "немає оцінок ще"
    else:
        basis = "у цій категорії" if stats["based_on"] == "category" else "по всіх категоріях"
        rating = f"{stats['avg_rating']:.1f}/5 {basis}"
    return (
        f"ID кандидата: {candidate.id}\n"
        f"Ім'я: {candidate.name}\n"
        f"Резюме: {resume}\n"
        f"Середній рейтинг: {rating}\n"
        f"Виконаних заявок: {stats['completed_count']}"
    )


def _select_with_claude(ticket, candidates, stats_by_id):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not set; falling back to rating-based technician assignment"
        )
        return _pick_best_by_rating(candidates, stats_by_id), None

    candidates_block = "\n\n".join(_format_candidate(c, stats_by_id[c.id]) for c in candidates)
    user_prompt = (
        f"Нова заявка:\n"
        f"Заголовок: {ticket.title}\n"
        f"Опис: {ticket.description or '—'}\n"
        f"Категорія: {ticket.category}\n"
        f"Пріоритет: {ticket.priority or '—'}\n\n"
        f"Кандидати:\n\n{candidates_block}"
    )

    # The SDK default read timeout is 600s (plus retries) - far too long to
    # block a ticket-creation web request, so cap it well below the request
    # timeout of whatever's fronting this app.
    client = anthropic.Anthropic(api_key=api_key, timeout=20.0, max_retries=1)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError:
        logger.exception(
            "Claude API call failed during technician selection for ticket #%s; "
            "falling back to rating-based assignment",
            ticket.id,
        )
        return _pick_best_by_rating(candidates, stats_by_id), None

    text = next((block.text for block in response.content if block.type == "text"), "")

    try:
        result = _extract_json(text)
        technician_id = int(result["technician_id"])
        reasoning = (result.get("reasoning") or "").strip() or None
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        logger.warning("Could not parse Claude technician-selection response: %r", text)
        return _pick_best_by_rating(candidates, stats_by_id), None

    chosen = next((c for c in candidates if c.id == technician_id), None)
    if chosen is None:
        logger.warning(
            "Claude picked technician_id=%r which is not among the candidates; falling back",
            technician_id,
        )
        return _pick_best_by_rating(candidates, stats_by_id), None

    return chosen, reasoning


def select_technician(ticket):
    """Pick the best available technician for `ticket`.

    Returns (technician_or_None, reasoning_or_None):
    - No matching/available technician: (None, None).
    - Exactly one candidate: assigned directly, no AI call, (technician, None).
    - Candidates exist but none has a resume_summary: falls back to the
      highest-rated candidate, no AI call, (technician, None).
    - Otherwise Claude picks among the candidates using their resume
      summaries and rating history, returning its reasoning. If the Claude
      call fails or returns something unusable, falls back to the
      highest-rated candidate, (technician, None).
    """
    candidates = Technician.query.filter_by(specialty=ticket.category, available=True).all()

    if not candidates:
        return None, None

    if len(candidates) == 1:
        return candidates[0], None

    stats_by_id = {c.id: _technician_stats(c.id, ticket.category) for c in candidates}

    if not any(c.resume_summary for c in candidates):
        return _pick_best_by_rating(candidates, stats_by_id), None

    return _select_with_claude(ticket, candidates, stats_by_id)
