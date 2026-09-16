"""ai_classifier.classify_ticket() - fallback behavior and response parsing,
against a mocked anthropic client (see tests/fakes.py) instead of a real
API call.
"""
import json

import ai_classifier
from tests.fakes import fake_anthropic_constructor


def test_no_api_key_returns_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = ai_classifier.classify_ticket("The kitchen sink is leaking")

    assert result == ai_classifier.FALLBACK_RESULT


def test_valid_response_is_parsed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    fake_text = json.dumps(
        {
            "categories": ["plumbing"],
            "priority": "high",
            "urgency_reason": "Active water leak.",
        }
    )
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text)
    )

    result = ai_classifier.classify_ticket("Water is pouring out from under the sink")

    assert result["category"] == "plumbing"
    assert result["categories"] == ["plumbing"]
    assert result["priority"] == "high"


def test_invalid_category_in_response_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    fake_text = json.dumps({"categories": ["not-a-real-category"], "priority": "high"})
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text)
    )

    result = ai_classifier.classify_ticket("Something broke")

    assert result == ai_classifier.FALLBACK_RESULT
