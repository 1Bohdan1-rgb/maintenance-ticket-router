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
    "priority": "medium",
    "urgency_reason": "Не вдалося класифікувати автоматично, застосовано значення за замовчуванням.",
}

SYSTEM_PROMPT = """You are a triage dispatcher for a building maintenance service.
Given the description of a maintenance issue, classify it.

Respond with STRICT JSON only. No markdown, no code fences, no explanation
before or after the JSON. Respond with exactly one JSON object of this shape:

{"category": "plumbing|electrical|carpentry|general", "priority": "low|medium|high|emergency", "urgency_reason": "one short sentence"}

Rules:
- "category" must be exactly one of: plumbing, electrical, carpentry, general.
- "priority" must be exactly one of: low, medium, high, emergency. Use "emergency"
  only when the issue poses an immediate safety or property risk (e.g. gas leak,
  active flooding, exposed live wiring, fire hazard).
- "urgency_reason" is a single short sentence explaining the assigned priority.
- The description may be in Ukrainian, English, or any other language - classify
  it regardless of language, and write "urgency_reason" in the same language as
  the description.
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found in Claude response")
    return json.loads(match.group(0))


def classify_ticket(description: str) -> dict:
    """Classify a maintenance ticket description via Claude.

    Always returns a dict with "category", "priority", and "urgency_reason".
    Falls back to category="general", priority="medium" on any failure
    (missing API key, network/API error, or an unparsable/invalid response).
    """
    if not description or not description.strip():
        return dict(FALLBACK_RESULT)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY is not set; using fallback classification")
        return dict(FALLBACK_RESULT)

    # The SDK default read timeout is 600s (plus retries) - far too long to
    # block a ticket-creation web request, so cap it well below the request
    # timeout of whatever's fronting this app.
    client = anthropic.Anthropic(api_key=api_key, timeout=20.0, max_retries=1)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": description}],
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

    category = result.get("category")
    priority = result.get("priority")
    urgency_reason = result.get("urgency_reason") or ""

    if category not in CATEGORIES or priority not in PRIORITIES:
        logger.warning("Claude returned an invalid category/priority: %r", result)
        return dict(FALLBACK_RESULT)

    return {
        "category": category,
        "priority": priority,
        "urgency_reason": urgency_reason,
    }
