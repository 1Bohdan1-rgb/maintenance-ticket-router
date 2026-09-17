import json
import logging
import os
import re

import anthropic

from models import CATEGORIES, PRIORITIES

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

FALLBACK_RESULT = {
    "category": "general",
    "categories": ["general"],
    "priority": "medium",
    "urgency_reason": "Не вдалося класифікувати автоматично, застосовано значення за замовчуванням.",
}

SYSTEM_PROMPT = """You are a triage dispatcher for a building maintenance service.
Given the description of a maintenance issue, classify it.

Respond with STRICT JSON only. No markdown, no code fences, no explanation
before or after the JSON. Respond with exactly one JSON object of this shape:

{"categories": ["plumbing|electrical|carpentry|general", "..."], "priority": "low|medium|high|emergency", "urgency_reason": "one short sentence"}

Rules:
- "categories" is a JSON array of one or more values, each exactly one of:
  plumbing, electrical, carpentry, general.
- Decide how many categories by asking: would ONE specialist, in ONE visit,
  plausibly address every symptom described? If yes, use a single-element
  array. If any symptom has a genuinely different underlying cause that
  specialist wouldn't touch, add a category for it too - even though it was
  reported in the same request.
  - A single root cause with a secondary symptom is usually ONE problem
    needing MULTIPLE trades on-site together: "the ceiling collapsed,
    exposing wiring and a burst pipe" needs carpentry, electrical, AND
    plumbing, because fixing the collapse itself requires all three.
  - Unrelated problems bundled into one request are SEPARATE problems even
    when only one of them is a clean trade match: "the boiler stopped
    heating water, and there's mold on the bedroom walls" needs plumbing
    (the boiler) AND general (the mold) - a plumber fixing the boiler does
    nothing about mold, which is usually a ventilation/humidity issue
    unrelated to the boiler, not a plumbing repair.
  - Mold, damp patches, condensation, or a musty smell are "general" by
    default - only call them "plumbing" or "carpentry" if the request
    itself also describes the actual leak/burst pipe/roof damage causing
    them. Don't fold them into whatever trade the *other* symptom needs
    just because dampness sounds water-related.
  Do not split an ordinary single-trade job into multiple categories just
  because it touches more than one fixture.
- List "categories" in order of how urgent/primary each trade is to the
  described problem.
- "priority" must be exactly one of: low, medium, high, emergency. Use "emergency"
  only when the issue poses an immediate safety or property risk (e.g. gas leak,
  active flooding, exposed live wiring, fire hazard).
- "urgency_reason" is a single short sentence explaining the assigned priority.
- The description may be in Ukrainian, English, or any other language - classify
  it regardless of language, and write "urgency_reason" in the same language as
  the description.
- A photo of the problem may be attached. Use it as additional visual
  evidence alongside the text - e.g. visibly exposed/scorched wiring
  implies electrical, a visible pipe leak or water pooling implies
  plumbing, damaged wood/drywall/framing implies carpentry - even if the
  text description doesn't mention it. If the photo and text point to
  different trades, include both in "categories".
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found in Claude response")
    return json.loads(match.group(0))


def classify_ticket(description: str, photo_data: str = None, photo_content_type: str = None) -> dict:
    """Classify a maintenance ticket description (and optional photo) via Claude.

    `photo_data` is a base64-encoded image (no "data:" prefix) and
    `photo_content_type` its MIME type (e.g. "image/jpeg") - pass both or
    neither. When given, the photo is sent alongside the text as visual
    context; classification still works from the photo alone if
    `description` is empty.

    Always returns a dict with "category" (str), "categories" (list of str,
    always at least one element), "priority", and "urgency_reason".
    "category" is always categories[0] - kept for callers that only need a
    single value, so behavior is unchanged whenever Claude (or the fallback)
    returns exactly one category. Falls back to categories=["general"],
    priority="medium" on any failure (missing API key, network/API error, or
    an unparsable/invalid response).
    """
    has_text = bool(description and description.strip())
    has_photo = bool(photo_data and photo_content_type)

    if not has_text and not has_photo:
        return dict(FALLBACK_RESULT)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY is not set; using fallback classification")
        return dict(FALLBACK_RESULT)

    if has_photo:
        content = [
            {
                "type": "text",
                "text": description if has_text else "(Клієнт не надав текстовий опис - лише фото.)",
            },
            {
                "type": "image",
                "source": {"type": "base64", "media_type": photo_content_type, "data": photo_data},
            },
        ]
    else:
        content = description

    # The SDK default read timeout is 600s (plus retries) - far too long to
    # block a ticket-creation web request, so cap it well below the request
    # timeout of whatever's fronting this app.
    client = anthropic.Anthropic(api_key=api_key, timeout=20.0, max_retries=1)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.NotFoundError:
        logger.exception("Claude API model/endpoint not found; using fallback classification")
        return dict(FALLBACK_RESULT)
    except anthropic.AuthenticationError:
        logger.exception("Claude API authentication failed; using fallback classification")
        return dict(FALLBACK_RESULT)
    except anthropic.RateLimitError:
        logger.exception("Claude API rate limited; using fallback classification")
        return dict(FALLBACK_RESULT)
    except anthropic.APIStatusError:
        logger.exception("Claude API returned an error status; using fallback classification")
        return dict(FALLBACK_RESULT)
    except anthropic.APIConnectionError:
        logger.exception("Network error calling Claude API; using fallback classification")
        return dict(FALLBACK_RESULT)

    text = next((block.text for block in response.content if block.type == "text"), "")

    try:
        result = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        logger.warning("Could not parse Claude response as JSON: %r", text)
        return dict(FALLBACK_RESULT)

    categories_raw = result.get("categories")
    priority = result.get("priority")
    urgency_reason = result.get("urgency_reason") or ""

    categories = []
    if isinstance(categories_raw, list):
        for c in categories_raw:
            if c in CATEGORIES and c not in categories:
                categories.append(c)

    if not categories or priority not in PRIORITIES:
        logger.warning("Claude returned invalid categories/priority: %r", result)
        return dict(FALLBACK_RESULT)

    return {
        "category": categories[0],
        "categories": categories,
        "priority": priority,
        "urgency_reason": urgency_reason,
    }
