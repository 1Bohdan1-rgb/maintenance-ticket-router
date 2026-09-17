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


def test_system_prompt_documents_unrelated_symptom_splitting():
    # Regression check for the "boiler + mold" bug: the prompt must keep
    # explicit guidance that unrelated symptoms bundled in one request are
    # separate categories, and that mold/dampness defaults to "general"
    # rather than being folded into whatever trade the other symptom needs.
    prompt = ai_classifier.SYSTEM_PROMPT
    assert "mold" in prompt.lower()
    assert "general" in prompt.lower()
    assert "unrelated" in prompt.lower()


def test_invalid_category_in_response_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    fake_text = json.dumps({"categories": ["not-a-real-category"], "priority": "high"})
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text)
    )

    result = ai_classifier.classify_ticket("Something broke")

    assert result == ai_classifier.FALLBACK_RESULT


def test_severity_is_parsed_alongside_category_and_priority(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    fake_text = json.dumps(
        {
            "categories": ["plumbing"],
            "priority": "low",
            "urgency_reason": "Minor drip.",
            "severity": 2,
            "severity_reason": "A single dripping tap, no visible damage.",
        }
    )
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text)
    )

    result = ai_classifier.classify_ticket("Kitchen tap is dripping")

    assert result["severity"] == 2
    assert result["severity_reason"] == "A single dripping tap, no visible damage."
    assert result["priority"] == "low"


def test_severity_5_forces_emergency_priority(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    fake_text = json.dumps(
        {
            "categories": ["carpentry"],
            "priority": "low",
            "urgency_reason": "Text undersold it.",
            "severity": 5,
            "severity_reason": "Photo shows a fully collapsed ceiling.",
        }
    )
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text)
    )

    result = ai_classifier.classify_ticket("Ceiling issue")

    assert result["severity"] == 5
    assert result["priority"] == "emergency"


def test_severity_4_forces_at_least_high_but_not_downgrade(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    fake_text_medium = json.dumps(
        {"categories": ["carpentry"], "priority": "medium", "severity": 4}
    )
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text_medium)
    )
    result = ai_classifier.classify_ticket("Large crack in the wall")
    assert result["priority"] == "high"

    # Claude already said "emergency" for other reasons - severity 4's
    # floor (only "high") must not downgrade it.
    fake_text_emergency = json.dumps(
        {"categories": ["carpentry"], "priority": "emergency", "severity": 4}
    )
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text_emergency)
    )
    result = ai_classifier.classify_ticket("Large crack in the wall, gas smell too")
    assert result["priority"] == "emergency"


def test_invalid_severity_falls_back_to_default_without_discarding_classification(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    fake_text = json.dumps(
        {"categories": ["plumbing"], "priority": "high", "severity": "very bad"}
    )
    monkeypatch.setattr(
        ai_classifier.anthropic, "Anthropic", fake_anthropic_constructor(fake_text)
    )

    result = ai_classifier.classify_ticket("Water everywhere")

    assert result["category"] == "plumbing"
    assert result["priority"] == "high"
    assert result["severity"] == 3


def test_fallback_result_includes_severity():
    assert ai_classifier.FALLBACK_RESULT["severity"] == 3
    assert ai_classifier.FALLBACK_RESULT["severity_reason"]
