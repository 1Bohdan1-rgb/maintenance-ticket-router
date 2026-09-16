"""POST /admin/reassign-pending - retries technician matching for
ticket_assignments rows still missing a technician, reusing each ticket's
own saved match_priority/preferred_gender rather than defaulting.
"""
from models import Technician, Ticket, TicketAssignment, db


def test_requires_admin_token(client):
    resp = client.post("/admin/reassign-pending")
    assert resp.status_code == 401


def test_fills_gap_using_ticket_saved_preferences(client, ctx, admin_headers):
    # Two plumbing candidates so the pick actually depends on the client's
    # stated priority instead of "only one candidate exists".
    budget = Technician(name="Budget Bob", specialty="plumbing", available=True, price_tier="budget")
    premium = Technician(name="Premium Pete", specialty="plumbing", available=True, price_tier="premium")
    db.session.add_all([budget, premium])
    db.session.commit()

    # Simulates a ticket created when no plumbing candidate was available
    # yet - one assignment row with technician_id=None - that also
    # recorded the client's original "price" priority.
    ticket = Ticket(
        title="Leaky tap", category="plumbing", status="pending_assignment",
        match_priority="price",
    )
    db.session.add(ticket)
    db.session.commit()
    db.session.add(TicketAssignment(ticket_id=ticket.id, technician_id=None, specialty="plumbing"))
    db.session.commit()

    resp = client.post("/admin/reassign-pending", headers=admin_headers)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["remaining_gaps"] == 0
    assert body["reassigned"][0]["technician"] == "Budget Bob"

    db.session.refresh(ticket)
    assert ticket.status == "assigned"
    assert Technician.query.get(ticket.assigned_to).name == "Budget Bob"
