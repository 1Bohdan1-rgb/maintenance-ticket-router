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

You will receive the ticket details, the client's stated priority (quality,
speed, or price), and a list of candidate technicians who already match the
required category and are available. Each candidate has a resume summary,
an average customer rating, a count of completed jobs, a typical price tier
(budget/mid/premium), and a typical speed rating (fast/medium/slow).

Pick the single best candidate based on how well their resume/experience
fits the specific issue described, weighed against their rating history -
then weigh that against the client's stated priority:
- "quality": resume fit and rating history decide it; price/speed are a
  tiebreaker at most.
- "speed": prefer a faster candidate, unless a slower one is a clearly
  better fit for the issue or meaningfully better rated.
- "price": prefer a cheaper candidate, unless a pricier one is a clearly
  better fit for the issue or meaningfully better rated.
A technician with little or no rating history is not automatically worse -
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

_PRICE_TIER_LABELS = {"budget": "бюджетна", "mid": "середня", "premium": "преміум"}
_SPEED_RATING_LABELS = {"fast": "швидко", "medium": "середньо", "slow": "повільно"}
_MATCH_PRIORITY_LABELS = {
    "quality": "якість виконання - найкращий фахівець під цю заявку, ціна/швидкість другорядні",
    "speed": "швидкість - клієнту важливо, щоб приїхали якнайшвидше",
    "price": "ціна - клієнт хоче заощадити",
}


def select_technician_team(ticket, categories, match_priority="quality", preferred_gender=None):
    """Pick one technician per required specialty for a (possibly
    multi-discipline) ticket.

    `categories` is the ordered, deduplicated list of specialties the
    ticket needs (from classify_ticket's "categories"). Each specialty is
    matched independently via select_technician(), reusing the exact same
    resume/rating/match_priority/gender-preference logic per specialty - no
    cross-specialty interaction is needed since a technician only ever has
    one specialty, so the same technician can never be picked twice across
    categories.

    Returns a list of (specialty, technician_or_None, reasoning_or_None)
    tuples, one per category, in the given order. For an ordinary
    single-category ticket this is a one-element list, identical in
    content to calling select_technician() directly.
    """
    return [
        (specialty,)
        + select_technician(
            ticket, match_priority=match_priority, specialty=specialty, preferred_gender=preferred_gender
        )
        for specialty in categories
    ]


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


def _filter_by_match_priority(candidates, match_priority):
    """Narrow candidates to the tier that best matches the client's chosen
    match_priority ("speed" or "price"; "quality" leaves the list as-is).

    Used only as the deterministic fallback (_fallback_pick) for when no AI
    signal is available at all - no candidate has a resume, no API key is
    configured, or the Claude call fails/is unusable. Whenever Claude does
    run, it sees the full candidate pool instead (with each candidate's
    price tier/speed rating and the client's priority spelled out in the
    prompt) and reasons about the trade-off itself, rather than having
    candidates discarded before it gets a say.

    Ranks candidates into three tiers - best match, neutral, worst match -
    and returns the best non-empty tier. A technician with the field unset
    (None) is treated as neutral, not excluded, same as the explicit middle
    value - this can never return an empty list since every candidate falls
    into exactly one tier.
    """
    if match_priority == "price":
        field, best, worst = "price_tier", "budget", "premium"
    elif match_priority == "speed":
        field, best, worst = "speed_rating", "fast", "slow"
    else:
        return candidates

    tiers = [
        [c for c in candidates if getattr(c, field) == best],
        [c for c in candidates if getattr(c, field) not in (best, worst)],
        [c for c in candidates if getattr(c, field) == worst],
    ]
    for tier in tiers:
        if tier:
            return tier
    return candidates


def _filter_by_gender_preference(candidates, preferred_gender):
    """Narrow candidates to the client's preferred technician gender, if
    one was given ("male" or "female"; None/omitted means no preference).

    Never blocks assignment: if no candidate has that gender on file, the
    full unfiltered list is returned instead of an empty one, so an unmet
    preference falls back to the normal resume/rating selection rather
    than leaving the ticket unassigned.
    """
    if not preferred_gender:
        return candidates
    matching = [c for c in candidates if c.gender == preferred_gender]
    return matching if matching else candidates


def _pick_best_by_rating(candidates, stats_by_id):
    def sort_key(technician):
        stats = stats_by_id[technician.id]
        avg = stats["avg_rating"]
        return (avg is None, -(avg or 0.0), -stats["completed_count"], technician.id)

    return sorted(candidates, key=sort_key)[0]


def _fallback_pick(candidates, stats_by_id, match_priority):
    """Deterministic pick used whenever no AI signal is available at all -
    no candidate has a resume, no API key is configured, or the Claude call
    failed/returned something unusable. Narrows by the client's price/speed
    tier first (see _filter_by_match_priority) since that's the only signal
    left to honor their stated priority, then picks the best-rated within
    that tier.
    """
    tiered = _filter_by_match_priority(candidates, match_priority)
    return _pick_best_by_rating(tiered, stats_by_id)


def _format_candidate(candidate, stats):
    resume = candidate.resume_summary or "Резюме-саммарі відсутнє."
    if stats["avg_rating"] is None:
        rating = "немає оцінок ще"
    else:
        basis = "у цій категорії" if stats["based_on"] == "category" else "по всіх категоріях"
        rating = f"{stats['avg_rating']:.1f}/5 {basis}"
    price_label = _PRICE_TIER_LABELS.get(candidate.price_tier, "не вказано")
    speed_label = _SPEED_RATING_LABELS.get(candidate.speed_rating, "не вказано")
    return (
        f"ID кандидата: {candidate.id}\n"
        f"Ім'я: {candidate.name}\n"
        f"Резюме: {resume}\n"
        f"Середній рейтинг: {rating}\n"
        f"Виконаних заявок: {stats['completed_count']}\n"
        f"Цінова категорія: {price_label}\n"
        f"Швидкість виконання: {speed_label}"
    )


def _select_with_claude(ticket, candidates, stats_by_id, specialty, match_priority):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not set; falling back to rating-based technician assignment"
        )
        return _fallback_pick(candidates, stats_by_id, match_priority), None

    candidates_block = "\n\n".join(_format_candidate(c, stats_by_id[c.id]) for c in candidates)
    priority_label = _MATCH_PRIORITY_LABELS.get(match_priority, _MATCH_PRIORITY_LABELS["quality"])
    user_prompt = (
        f"Нова заявка:\n"
        f"Заголовок: {ticket.title}\n"
        f"Опис: {ticket.description or '—'}\n"
        f"Потрібна спеціальність для цього призначення: {specialty}\n"
        f"Пріоритет заявки: {ticket.priority or '—'}\n"
        f"Що найважливіше для клієнта: {priority_label}\n\n"
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
        return _fallback_pick(candidates, stats_by_id, match_priority), None

    text = next((block.text for block in response.content if block.type == "text"), "")

    try:
        result = _extract_json(text)
        technician_id = int(result["technician_id"])
        reasoning = (result.get("reasoning") or "").strip() or None
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        logger.warning("Could not parse Claude technician-selection response: %r", text)
        return _fallback_pick(candidates, stats_by_id, match_priority), None

    chosen = next((c for c in candidates if c.id == technician_id), None)
    if chosen is None:
        logger.warning(
            "Claude picked technician_id=%r which is not among the candidates; falling back",
            technician_id,
        )
        return _fallback_pick(candidates, stats_by_id, match_priority), None

    return chosen, reasoning


def select_technician(ticket, match_priority="quality", specialty=None, preferred_gender=None, exclude_ids=None):
    """Pick the best available technician for `ticket` in one specialty.

    `specialty` defaults to `ticket.category` (the ticket's primary/only
    specialty) - pass it explicitly to match a specific discipline on a
    multi-discipline ticket (see select_technician_team).

    `exclude_ids` (an iterable of technician ids, or None) removes those
    candidates from the pool entirely before anything else runs - used when
    re-picking after a technician declines their assignment, so they can't
    just be handed straight back the same ticket.

    `match_priority` is the client's stated preference - "quality" (default),
    "speed", or "price". Whenever Claude gets to weigh in, it sees the full
    candidate pool - including each candidate's price tier/speed rating and
    the client's stated priority spelled out in the prompt - and reasons
    about the trade-off against resume fit and rating itself, rather than
    having candidates discarded before it gets a say. Only when no AI
    signal is available at all (see _fallback_pick below) does "speed"/
    "price" fall back to a deterministic tier filter; "quality" never
    narrows the pool.

    `preferred_gender` ("male", "female", or None) narrows the pool before
    stats/AI selection, non-blocking fallback behavior (see
    _filter_by_gender_preference) - an unmet preference never leaves the
    ticket unassigned.

    Returns (technician_or_None, reasoning_or_None):
    - No matching/available technician: (None, None).
    - Exactly one candidate (before or after gender narrowing): assigned
      directly, no AI call, (technician, None).
    - Candidates exist but none has a resume_summary: no AI call, falls
      back to the client's price/speed tier then highest rating (see
      _fallback_pick), (technician, None).
    - Otherwise Claude picks among the candidates using their resume
      summaries, rating history, price tier, and speed rating, weighed
      against match_priority, returning its reasoning. If the Claude call
      fails or returns something unusable, falls back the same way as the
      no-resume case, (technician, None).
    """
    specialty = specialty or ticket.category
    candidates = Technician.query.filter_by(specialty=specialty, available=True).all()

    if exclude_ids:
        candidates = [c for c in candidates if c.id not in exclude_ids]

    if not candidates:
        return None, None

    if len(candidates) == 1:
        return candidates[0], None

    candidates = _filter_by_gender_preference(candidates, preferred_gender)

    if len(candidates) == 1:
        return candidates[0], None

    stats_by_id = {c.id: _technician_stats(c.id, specialty) for c in candidates}

    if not any(c.resume_summary for c in candidates):
        return _fallback_pick(candidates, stats_by_id, match_priority), None

    return _select_with_claude(ticket, candidates, stats_by_id, specialty, match_priority)
