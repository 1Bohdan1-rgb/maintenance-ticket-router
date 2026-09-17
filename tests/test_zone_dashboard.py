"""Phase-2 "pull" dashboard: /technician/dashboard surfaces open assignment
slots within the technician's own service radius (_open_assignments_in_zone),
and POST /technician/assignments/<id>/claim lets them self-assign one -
distinct from the automatic "push" assignment done at ticket creation.
"""
from models import Technician, Ticket, TicketAssignment, db
from routes import _open_assignments_in_zone

KYIV = (50.4501, 30.5234)
LVIV = (49.8397, 24.0297)


def _zone_technician(radius_km=20, email="zoya@example.com"):
    technician = Technician(
        name="Zone Zoya", specialty="plumbing", available=True,
        lat=KYIV[0], lng=KYIV[1], service_radius_km=radius_km,
        email=email, phone="+380671112233",
    )
    db.session.add(technician)
    db.session.commit()
    return technician


def _open_ticket(specialty="plumbing", lat=KYIV[0], lng=KYIV[1], status="pending_assignment"):
    ticket = Ticket(
        title="Leaky tap", category=specialty, status=status,
        customer_lat=lat, customer_lng=lng,
    )
    db.session.add(ticket)
    db.session.commit()
    db.session.add(TicketAssignment(ticket_id=ticket.id, technician_id=None, specialty=specialty))
    db.session.commit()
    return ticket


def test_open_assignment_within_radius_appears_in_zone(ctx):
    technician = _zone_technician()
    ticket = _open_ticket()

    zone = _open_assignments_in_zone(technician)

    assert len(zone) == 1
    assignment, distance_km = zone[0]
    assert assignment.ticket_id == ticket.id
    assert distance_km < 1


def test_out_of_radius_ticket_is_excluded(ctx):
    technician = _zone_technician(radius_km=20)
    _open_ticket(lat=LVIV[0], lng=LVIV[1])

    assert _open_assignments_in_zone(technician) == []


def test_already_assigned_slot_is_excluded(ctx):
    technician = _zone_technician()
    ticket = _open_ticket()
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()
    other = Technician(name="Other Tech", specialty="plumbing", available=True)
    db.session.add(other)
    db.session.commit()
    assignment.technician_id = other.id
    db.session.commit()

    assert _open_assignments_in_zone(technician) == []


def test_technician_without_location_sees_no_zone(ctx):
    technician = Technician(name="No Zone", specialty="plumbing", available=True, email="nz@example.com")
    db.session.add(technician)
    db.session.commit()
    _open_ticket()

    assert _open_assignments_in_zone(technician) == []


def test_wrong_specialty_is_excluded(ctx):
    technician = _zone_technician()
    _open_ticket(specialty="electrical")

    assert _open_assignments_in_zone(technician) == []


def test_unavailable_technician_sees_no_zone(ctx):
    technician = _zone_technician()
    technician.available = False
    db.session.commit()
    _open_ticket()

    assert _open_assignments_in_zone(technician) == []


def test_claim_rejected_for_unavailable_technician(client, ctx):
    technician = _zone_technician()
    ticket = _open_ticket()
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()
    technician.available = False
    db.session.commit()

    resp = client.post(
        f"/technician/assignments/{assignment.id}/claim",
        data={"email": technician.email},
    )

    assert resp.status_code == 200
    db.session.refresh(assignment)
    assert assignment.technician_id is None
    assert "недоступний" in resp.get_data(as_text=True)


def test_claim_assigns_technician_and_updates_ticket_status(client, ctx):
    technician = _zone_technician()
    ticket = _open_ticket()
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()

    resp = client.post(
        f"/technician/assignments/{assignment.id}/claim",
        data={"email": technician.email},
    )

    assert resp.status_code == 200
    db.session.refresh(ticket)
    db.session.refresh(assignment)
    assert assignment.technician_id == technician.id
    assert ticket.assigned_to == technician.id
    assert ticket.status == "assigned"


def test_claim_rejects_already_taken_slot(client, ctx):
    technician = _zone_technician()
    ticket = _open_ticket()
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()
    assignment.technician_id = technician.id
    db.session.commit()

    other = Technician(
        name="Late Larry", specialty="plumbing", available=True, email="larry@example.com",
        lat=KYIV[0], lng=KYIV[1], service_radius_km=20,
    )
    db.session.add(other)
    db.session.commit()

    resp = client.post(
        f"/technician/assignments/{assignment.id}/claim",
        data={"email": other.email},
    )

    assert resp.status_code == 200
    assert "вже взяв інший майстер" in resp.get_data(as_text=True)


def test_claim_rejects_wrong_specialty(client, ctx):
    technician = _zone_technician()  # plumbing
    ticket = _open_ticket(specialty="electrical")
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket.id).first()

    resp = client.post(
        f"/technician/assignments/{assignment.id}/claim",
        data={"email": technician.email},
    )

    assert resp.status_code == 200
    db.session.refresh(assignment)
    assert assignment.technician_id is None
