"""technician_assignment.select_technician() - match_priority/preferred_gender
behavior, both the deterministic fallback (no AI signal available) and the
Claude-driven path against a mocked client.
"""
import json

import technician_assignment
from models import Technician, Ticket, db
from tests.fakes import fake_anthropic_constructor


def _make_ticket(category="plumbing", priority="low", title="Leaky tap", description="dripping"):
    ticket = Ticket(title=title, description=description, category=category, priority=priority)
    db.session.add(ticket)
    db.session.commit()
    return ticket


def test_single_candidate_is_assigned_without_ai_call(ctx, monkeypatch):
    # Seeded technicians already give exactly one plumbing candidate
    # (Oksana) - select_technician must return her directly, without
    # ever touching the anthropic client.
    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("anthropic.Anthropic should not be called for a single candidate")

    monkeypatch.setattr(technician_assignment.anthropic, "Anthropic", _should_not_be_called)

    ticket = _make_ticket()
    technician, reasoning = technician_assignment.select_technician(ticket, specialty="plumbing")

    assert technician.name == "Oksana Melnyk"
    assert reasoning is None


def test_price_priority_falls_back_to_budget_tier_without_ai_signal(ctx, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    budget = Technician(name="Budget Bob", specialty="plumbing", available=True, price_tier="budget")
    premium = Technician(name="Premium Pete", specialty="plumbing", available=True, price_tier="premium")
    db.session.add_all([budget, premium])
    db.session.commit()

    ticket = _make_ticket()
    technician, _ = technician_assignment.select_technician(
        ticket, match_priority="price", specialty="plumbing"
    )

    # Neither candidate has a resume, so no AI call is made at all - the
    # deterministic tier fallback must pick the budget-tier technician.
    assert technician.name == "Budget Bob"


def test_gender_preference_filters_candidates(ctx):
    male_tech = Technician(name="Male Tech", specialty="plumbing", available=True, gender="male")
    female_tech = Technician(name="Female Tech", specialty="plumbing", available=True, gender="female")
    db.session.add_all([male_tech, female_tech])
    db.session.commit()

    ticket = _make_ticket()
    technician, _ = technician_assignment.select_technician(
        ticket, specialty="plumbing", preferred_gender="female"
    )

    assert technician.name == "Female Tech"


def test_claude_selection_uses_mocked_response(ctx, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    budget = Technician(
        name="Budget Bob", specialty="plumbing", available=True,
        price_tier="budget", resume_summary="Basic tap repairs.",
    )
    premium = Technician(
        name="Premium Pete", specialty="plumbing", available=True,
        price_tier="premium", resume_summary="Emergency high-pressure pipe bursts.",
    )
    db.session.add_all([budget, premium])
    db.session.commit()

    fake_text = json.dumps(
        {"technician_id": premium.id, "reasoning": "Better fit for this emergency."}
    )
    monkeypatch.setattr(
        technician_assignment.anthropic, "Anthropic", fake_anthropic_constructor(fake_text)
    )

    ticket = _make_ticket(priority="emergency", description="Burst pipe under pressure")
    technician, reasoning = technician_assignment.select_technician(
        ticket, match_priority="price", specialty="plumbing"
    )

    assert technician.name == "Premium Pete"
    assert reasoning == "Better fit for this emergency."
