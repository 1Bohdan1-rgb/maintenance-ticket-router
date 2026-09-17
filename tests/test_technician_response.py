"""Technician accept/decline flow: confirm_ticket() moves a ticket into
"pending_technician_response" instead of straight to "confirmed", and
POST /technician/tickets/<id>/respond lets the assigned technician accept
(-> confirmed) or decline (-> immediately reassigned to another candidate,
or a gap if none exists).
"""
from models import Technician, Ticket, TicketAssignment, db


def _ticket_with_assignment(technician, specialty="plumbing", status="assigned"):
    ticket = Ticket(
        title="Leaky tap", category=specialty, status=status, assigned_to=technician.id,
    )
    db.session.add(ticket)
    db.session.commit()
    db.session.add(
        TicketAssignment(ticket_id=ticket.id, technician_id=technician.id, specialty=specialty)
    )
    db.session.commit()
    return ticket


def test_confirm_moves_to_pending_technician_response(client, ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _ticket_with_assignment(oksana)

    resp = client.post(f"/tickets/{ticket.id}/confirm")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pending_technician_response"
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()
    assert assignment.response_status == "pending"


def test_technician_accept_confirms_ticket(client, ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _ticket_with_assignment(oksana)
    client.post(f"/tickets/{ticket.id}/confirm")

    resp = client.post(
        f"/technician/tickets/{ticket.id}/respond",
        data={"email": oksana.email, "response": "accept"},
    )

    assert resp.status_code == 200
    db.session.refresh(ticket)
    assert ticket.status == "confirmed"
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()
    assert assignment.response_status == "accepted"


def test_technician_decline_reassigns_to_other_candidate(client, ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()
    premium_pete = Technician(name="Premium Pete", specialty="plumbing", available=True)
    db.session.add(premium_pete)
    db.session.commit()

    ticket = _ticket_with_assignment(oksana)
    client.post(f"/tickets/{ticket.id}/confirm")

    resp = client.post(
        f"/technician/tickets/{ticket.id}/respond",
        data={"email": oksana.email, "response": "decline"},
    )

    assert resp.status_code == 200
    db.session.refresh(ticket)
    assert ticket.status == "pending_technician_response"
    assert ticket.assigned_to == premium_pete.id

    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()
    assert assignment.technician_id == premium_pete.id
    assert assignment.response_status == "pending"


def test_technician_decline_with_no_other_candidate_leaves_gap(client, ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _ticket_with_assignment(oksana)
    client.post(f"/tickets/{ticket.id}/confirm")

    resp = client.post(
        f"/technician/tickets/{ticket.id}/respond",
        data={"email": oksana.email, "response": "decline"},
    )

    assert resp.status_code == 200
    db.session.refresh(ticket)
    assert ticket.status == "pending_assignment"
    assert ticket.assigned_to is None

    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()
    assert assignment.technician_id is None


def test_respond_rejected_when_ticket_not_awaiting_response(client, ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()
    # Never confirmed - still "assigned", so no assignment row is "pending" yet.
    ticket = _ticket_with_assignment(oksana)

    resp = client.post(
        f"/technician/tickets/{ticket.id}/respond",
        data={"email": oksana.email, "response": "accept"},
    )

    assert resp.status_code == 200
    db.session.refresh(ticket)
    assert ticket.status == "assigned"


def test_complete_blocked_while_awaiting_technician_response(client, ctx):
    oksana = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _ticket_with_assignment(oksana)
    client.post(f"/tickets/{ticket.id}/confirm")

    resp = client.post(
        f"/technician/tickets/{ticket.id}/complete", data={"email": oksana.email}
    )

    assert resp.status_code == 200
    db.session.refresh(ticket)
    assert ticket.status == "pending_technician_response"
