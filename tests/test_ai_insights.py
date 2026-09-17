"""ai_insights.get_ai_insights() - caching behavior and response parsing,
against a mocked anthropic client (see tests/fakes.py) instead of a real
API call.
"""
import json

import ai_insights
from tests.fakes import fake_anthropic_constructor


def _reset_cache():
    ai_insights._cache["insights"] = None
    ai_insights._cache["generated_at"] = 0.0


def test_no_api_key_returns_empty_list(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _reset_cache()

    result = ai_insights.get_ai_insights({"total_tickets": 5})

    assert result == []


def test_valid_response_is_parsed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    _reset_cache()
    fake_text = json.dumps(["Nadia has 3x the workload of Ivan.", "Emergency tickets spiked this week."])
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(fake_text))

    result = ai_insights.get_ai_insights({"total_tickets": 5})

    assert result == ["Nadia has 3x the workload of Ivan.", "Emergency tickets spiked this week."]


def test_result_is_cached_within_ttl(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    _reset_cache()

    calls = {"count": 0}

    def make_client(*args, **kwargs):
        calls["count"] += 1
        return fake_anthropic_constructor(json.dumps(["first"]))(*args, **kwargs)

    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", make_client)

    first = ai_insights.get_ai_insights({"total_tickets": 5})
    second = ai_insights.get_ai_insights({"total_tickets": 999})  # different stats, still cached

    assert first == ["first"]
    assert second == ["first"]
    assert calls["count"] == 1


def test_expired_cache_triggers_regeneration(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    _reset_cache()
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(json.dumps(["old"])))
    ai_insights.get_ai_insights({"total_tickets": 5})

    # Simulate the cache having gone stale.
    ai_insights._cache["generated_at"] -= ai_insights.CACHE_TTL_SECONDS + 1
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(json.dumps(["new"])))

    result = ai_insights.get_ai_insights({"total_tickets": 5})

    assert result == ["new"]


def test_failed_generation_falls_back_to_previous_cache(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    _reset_cache()
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(json.dumps(["kept"])))
    ai_insights.get_ai_insights({"total_tickets": 5})
    ai_insights._cache["generated_at"] -= ai_insights.CACHE_TTL_SECONDS + 1

    # This time Claude returns unparsable garbage - generation "fails".
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor("not json"))

    result = ai_insights.get_ai_insights({"total_tickets": 5})

    assert result == ["kept"]


def test_force_refresh_bypasses_cache(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    _reset_cache()
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(json.dumps(["first"])))
    ai_insights.get_ai_insights({"total_tickets": 5})

    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(json.dumps(["forced"])))
    result = ai_insights.get_ai_insights({"total_tickets": 5}, force_refresh=True)

    assert result == ["forced"]


def test_empty_array_is_a_valid_cached_result(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    _reset_cache()
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(json.dumps([])))

    result = ai_insights.get_ai_insights({"total_tickets": 0})

    assert result == []
    assert ai_insights._cache["insights"] == []
