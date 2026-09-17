"""GET /analytics - admin auth gate, and _build_analytics_stats()'s
aggregation logic (workload, distributions, decline rate).
"""
import base64
import json

import ai_insights
from models import Technician, Ticket, TicketAssignment, db
from routes import _build_analytics_stats
from tests.conftest import ADMIN_TOKEN
from tests.fakes import fake_anthropic_constructor


def test_analytics_requires_basic_auth(client):
    resp = client.get("/analytics")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("WWW-Authenticate", "")


def test_analytics_renders_with_correct_auth(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    creds = base64.b64encode(f"admin:{ADMIN_TOKEN}".encode()).decode()

    resp = client.get("/analytics", headers={"Authorization": f"Basic {creds}"})

    assert resp.status_code == 200
    assert b"chart.js" in resp.data.lower() or b"Chart" in resp.data


def test_workload_counts_active_and_completed_separately(ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()

    active = Ticket(title="a", category="plumbing", status="assigned", assigned_to=oksana.id)
    completed = Ticket(title="b", category="plumbing", status="completed", assigned_to=oksana.id)
    db.session.add_all([active, completed])
    db.session.commit()
    db.session.add_all([
        TicketAssignment(ticket_id=active.id, technician_id=oksana.id, specialty="plumbing"),
        TicketAssignment(ticket_id=completed.id, technician_id=oksana.id, specialty="plumbing"),
    ])
    db.session.commit()

    stats = _build_analytics_stats()
    row = next(r for r in stats["technician_workload"] if r["name"] == "Oksana Melnyk")

    assert row["active"] == 1
    assert row["completed"] == 1


def test_category_priority_severity_counts(ctx):
    db.session.add_all([
        Ticket(title="a", category="plumbing", priority="emergency", severity=5),
        Ticket(title="b", category="plumbing", priority="low", severity=1),
        Ticket(title="c", category="electrical", priority="high", severity=4),
    ])
    db.session.commit()

    stats = _build_analytics_stats()

    assert stats["category_counts"]["plumbing"] == 2
    assert stats["category_counts"]["electrical"] == 1
    assert stats["priority_counts"]["emergency"] == 1
    assert stats["priority_counts"]["low"] == 1
    assert stats["severity_counts"]["5"] == 1
    assert stats["severity_counts"]["1"] == 1
    assert stats["severity_counts"]["4"] == 1


def test_decline_rate_uses_persisted_decline_count(ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()
    ticket = Ticket(title="a", category="plumbing", status="confirmed", assigned_to=oksana.id)
    db.session.add(ticket)
    db.session.commit()
    # One assignment that was declined twice before finally being accepted -
    # decline_count must survive that, unlike response_status.
    db.session.add(
        TicketAssignment(
            ticket_id=ticket.id, technician_id=oksana.id, specialty="plumbing",
            response_status="accepted", decline_count=2,
        )
    )
    db.session.commit()

    stats = _build_analytics_stats()

    assert stats["decline_count"] == 2
    assert stats["accepted_count"] == 1
    assert stats["decline_rate_percent"] == round(100 * 2 / 3, 1)


def test_stats_are_json_serializable_for_the_ai_insights_call(ctx, monkeypatch):
    # The same stats dict is fed straight to Claude (see ai_insights) - make
    # sure nothing in it (e.g. an OrderedDict, a non-string dict key) trips
    # up json.dumps.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(ai_insights.anthropic, "Anthropic", fake_anthropic_constructor(json.dumps(["ok"])))
    ai_insights._cache["insights"] = None
    ai_insights._cache["generated_at"] = 0.0

    stats = _build_analytics_stats()
    result = ai_insights.get_ai_insights(stats)

    assert result == ["ok"]
