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
    "severity": 3,
    "severity_reason": "Не вдалося оцінити серйозність автоматично, застосовано середнє значення.",
}

# severity -> the minimum priority that severity level forces, regardless
# of what the text description alone would otherwise suggest - a
# deterministic backstop under the prompt's own instruction to Claude to
# do the same, in case it doesn't.
_SEVERITY_PRIORITY_FLOOR = {5: "emergency", 4: "high"}

SYSTEM_PROMPT = """You are a triage dispatcher for a building maintenance service.
Given the description of a maintenance issue, classify it.

Respond with STRICT JSON only. No markdown, no code fences, no explanation
before or after the JSON. Respond with exactly one JSON object of this shape:

{"categories": ["plumbing|electrical|carpentry|general", "..."], "priority": "low|medium|high|emergency", "urgency_reason": "one short sentence", "severity": 1-5, "severity_reason": "one short sentence"}

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
- "severity" is an integer from 1 to 5 rating the SCALE of physical damage
  or disrepair - independent of "priority":
    1 = cosmetic/trivial (a dripping tap, a loose handle, a small scuff)
    2 = minor (one broken fixture, small superficial damage)
    3 = moderate (a fixture failure affecting normal use, localized damage
        - e.g. one water-stained ceiling tile, a cracked pane)
    4 = major (significant damage, several affected fixtures/areas, or
        damage likely to worsen without prompt repair - e.g. a bowing
        ceiling, extensive water staining, a large structural crack)
    5 = critical (structural failure, extensive destruction, or a
        collapse/major property-loss risk - e.g. a caved-in ceiling,
        widespread flooding, charred structural members)
  "priority" is about how urgently/safely someone must respond (a small gas
  smell is high priority for safety even with no visible damage yet);
  "severity" is purely about how much physical damage/disrepair already
  exists. They usually move together but not always - keep them independent.
  If "severity" is 5, "priority" must be "emergency". If "severity" is 4,
  "priority" must be at least "high". A large-scale physical problem is
  urgent even when the text description undersells it - reflect that
  reasoning in "urgency_reason".
- "severity_reason" is a single short sentence justifying the severity
  score, in the same language as the description. If a photo is attached,
  base it primarily on what's visible - the materials affected, the
  extent/area of the damage, and how far the deterioration has progressed;
  otherwise infer it from the text description alone.
- The description may be in Ukrainian, English, or any other language - classify
  it regardless of language, and write "urgency_reason" and "severity_reason" in
  the same language as the description.
- A photo of the problem may be attached. Use it as additional visual
  evidence alongside the text - e.g. visibly exposed/scorched wiring
  implies electrical, a visible pipe leak or water pooling implies
  plumbing, damaged wood/drywall/framing implies carpentry - even if the
  text description doesn't mention it. If the photo and text point to
  different trades, include both in "categories". The photo is also your
  primary evidence for "severity" - a photo showing more extensive damage
  than the text implies should push severity (and therefore priority)
  higher.
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
    always at least one element), "priority", "urgency_reason", "severity"
    (int, 1-5 - the scale of physical damage/disrepair, independent of how
    urgently it needs a response) and "severity_reason". "category" is
    always categories[0] - kept for callers that only need a single value,
    so behavior is unchanged whenever Claude (or the fallback) returns
    exactly one category. A severity of 4 or 5 forces "priority" up to at
    least "high"/"emergency" respectively, even if Claude's own priority
    call (or the text alone) undersold it - see _SEVERITY_PRIORITY_FLOOR.
    Falls back to categories=["general"], priority="medium", severity=3 on
    any failure (missing API key, network/API error, or an
    unparsable/invalid response); an invalid severity alone (valid
    category/priority) falls back to severity=3 without discarding the
    rest of the classification.
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
    severity_raw = result.get("severity")
    severity_reason = result.get("severity_reason") or ""

    categories = []
    if isinstance(categories_raw, list):
        for c in categories_raw:
            if c in CATEGORIES and c not in categories:
                categories.append(c)

    if not categories or priority not in PRIORITIES:
        logger.warning("Claude returned invalid categories/priority: %r", result)
        return dict(FALLBACK_RESULT)

    # severity is validated separately from categories/priority and falls
    # back to the neutral default (3) rather than discarding an otherwise
    # valid classification - an AI hiccup on this one field shouldn't nuke
    # a perfectly good category/priority call.
    severity = severity_raw if isinstance(severity_raw, int) and 1 <= severity_raw <= 5 else 3
    if severity != severity_raw:
        logger.warning("Claude returned invalid severity: %r; defaulting to 3", severity_raw)
        severity_reason = severity_reason or FALLBACK_RESULT["severity_reason"]

    floor = _SEVERITY_PRIORITY_FLOOR.get(severity)
    if floor and PRIORITIES.index(floor) > PRIORITIES.index(priority):
        priority = floor

    return {
        "category": categories[0],
        "categories": categories,
        "priority": priority,
        "urgency_reason": urgency_reason,
        "severity": severity,
        "severity_reason": severity_reason,
    }
