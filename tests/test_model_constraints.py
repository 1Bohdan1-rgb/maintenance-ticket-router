"""SQLite (the test DB) doesn't enforce VARCHAR(n) length at all, so a
status/enum value too long for its column only breaks on Postgres - caught
that the hard way with "pending_technician_response" (28 chars) not
fitting the original tickets.status VARCHAR(20). These tests catch the
next one before it reaches prod.
"""
from models import (
    GENDERS,
    MATCH_PRIORITIES,
    PRICE_TIERS,
    SPEED_RATINGS,
    STATUSES,
    Ticket,
    TicketAssignment,
)


def test_status_values_fit_column_length():
    max_len = Ticket.__table__.c.status.type.length
    too_long = [s for s in STATUSES if len(s) > max_len]
    assert not too_long, f"STATUSES values exceed tickets.status VARCHAR({max_len}): {too_long}"


def test_response_status_values_fit_column_length():
    max_len = TicketAssignment.__table__.c.response_status.type.length
    values = ["pending", "accepted", "declined"]
    too_long = [v for v in values if len(v) > max_len]
    assert not too_long, (
        f"response_status values exceed ticket_assignments.response_status "
        f"VARCHAR({max_len}): {too_long}"
    )


def test_match_priority_and_gender_values_fit_column_length():
    max_match_len = Ticket.__table__.c.match_priority.type.length
    max_gender_len = Ticket.__table__.c.preferred_gender.type.length
    too_long_priority = [v for v in MATCH_PRIORITIES if len(v) > max_match_len]
    too_long_gender = [v for v in GENDERS if len(v) > max_gender_len]
    assert not too_long_priority
    assert not too_long_gender


def test_price_tier_and_speed_rating_values_fit_column_length():
    from models import Technician

    max_price_len = Technician.__table__.c.price_tier.type.length
    max_speed_len = Technician.__table__.c.speed_rating.type.length
    too_long_price = [v for v in PRICE_TIERS if len(v) > max_price_len]
    too_long_speed = [v for v in SPEED_RATINGS if len(v) > max_speed_len]
    assert not too_long_price
    assert not too_long_speed
