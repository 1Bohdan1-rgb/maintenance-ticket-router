import json
import logging
import os
import re
import time

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

# How long a generated set of insights stays valid before the next page
# load triggers a fresh Claude call - keeps this off the hot path of every
# refresh while still feeling reasonably current.
CACHE_TTL_SECONDS = 20 * 60

SYSTEM_PROMPT = """You are a business analyst for a building maintenance
dispatch service. You will receive a JSON object of already-aggregated
statistics - ticket counts by category/priority/severity, per-technician
workload, average time-to-assignment/time-to-confirmation, a technician
decline rate, and a recent daily ticket-count trend. You will never
receive raw ticket text or customer data.

Look for genuinely notable patterns - not a restatement of the numbers:
- A category or priority skewed heavily compared to the others
- A technician who is overloaded or idle relative to their peers
- An unusually high share of severe (4-5) tickets
- A decline rate worth flagging
- A spike or dip in the daily trend

Respond with STRICT JSON only - no markdown, no code fences, no
explanation before or after. Respond with a JSON array of 2 to 4 short
strings, each one sentence, written in Ukrainian. If the data is too
sparse or uniform to say anything genuinely useful, return fewer,
shorter observations rather than padding with generic filler - an empty
array is a valid response.
"""

_cache = {"insights": None, "generated_at": 0.0, "stats_signature": None}


def _extract_json_array(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON array found in Claude response")
    return json.loads(match.group(0))


def _generate_insights(stats):
    """Returns a list of 0-4 insight strings, or None if generation failed
    outright (no API key, API error, unparsable response) - None is
    distinct from a legitimate empty list (Claude looked at the data and
    genuinely had nothing notable to say), so the cache below never treats
    a transient failure as if it were that valid "nothing to report" answer.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY is not set; skipping AI insights")
        return None

    client = anthropic.Anthropic(api_key=api_key, timeout=20.0, max_retries=1)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(stats, ensure_ascii=False)}],
        )
    except anthropic.APIError:
        logger.exception("Claude API call failed while generating AI insights")
        return None

    text = next((block.text for block in response.content if block.type == "text"), "")

    try:
        result = _extract_json_array(text)
    except (ValueError, json.JSONDecodeError):
        logger.warning("Could not parse AI insights response as a JSON array: %r", text)
        return None

    if not isinstance(result, list):
        logger.warning("AI insights response was not a JSON array: %r", result)
        return None

    return [str(item).strip() for item in result if str(item).strip()][:4]


def get_ai_insights(stats, force_refresh=False):
    """Returns 0-4 short natural-language observations about `stats` (a
    JSON-serializable dict of aggregated analytics - never raw ticket/
    customer data). Cached in-process for CACHE_TTL_SECONDS so a page
    refresh doesn't re-trigger a Claude call every time; the cache is keyed
    only on time, not on whether `stats` changed, per the "regenerate at
    most every ~20 minutes" requirement - not a content hash.

    A failed generation (no API key, API error, unparsable response) never
    overwrites the cache - it falls back to whatever was cached before
    (stale but real insights beat a blank panel), or [] on a cold start -
    and the *next* request tries again rather than being locked out for a
    full TTL window by one transient failure.
    """
    now = time.time()
    if (
        not force_refresh
        and _cache["insights"] is not None
        and (now - _cache["generated_at"]) < CACHE_TTL_SECONDS
    ):
        return _cache["insights"]

    insights = _generate_insights(stats)
    if insights is None:
        return _cache["insights"] or []

    _cache["insights"] = insights
    _cache["generated_at"] = now
    return insights
