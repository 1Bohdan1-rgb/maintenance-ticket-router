"""POST /tickets - required fields and email/phone format validation.

ANTHROPIC_API_KEY is unset by the `app` fixture, so classify_ticket() takes
its deterministic fallback path (category="general", priority="medium")
without a network call - these tests aren't about classification, just the
request-validation and persistence behavior around it.
"""


def test_missing_title_returns_400(client):
    resp = client.post("/tickets", json={"customer_email": "a@example.com"})
    assert resp.status_code == 400


def test_no_contact_info_returns_400(client):
    resp = client.post("/tickets", json={"title": "Leaky tap"})
    assert resp.status_code == 400


def test_invalid_email_format_returns_400(client):
    resp = client.post("/tickets", json={"title": "Leaky tap", "customer_email": "not-an-email"})
    assert resp.status_code == 400


def test_invalid_phone_format_returns_400(client):
    resp = client.post("/tickets", json={"title": "Leaky tap", "customer_phone": "abc"})
    assert resp.status_code == 400


def test_valid_ticket_persists_match_priority_and_gender(client, ctx):
    from models import Ticket

    resp = client.post(
        "/tickets",
        json={
            "title": "Leaky tap",
            "description": "Kitchen tap is dripping",
            "customer_email": "customer@example.com",
            "match_priority": "price",
            "preferred_gender": "female",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["match_priority"] == "price"
    assert data["preferred_gender"] == "female"

    ticket = Ticket.query.get(data["id"])
    assert ticket.match_priority == "price"
    assert ticket.preferred_gender == "female"


def test_address_is_geocoded_and_persisted(client, ctx, monkeypatch):
    import routes
    from models import Ticket

    monkeypatch.setattr(routes, "geocode_address", lambda address: (50.45, 30.52))

    resp = client.post(
        "/tickets",
        json={
            "title": "Leaky tap",
            "customer_email": "customer@example.com",
            "customer_address": "1 Khreshchatyk St, Kyiv",
        },
    )

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["customer_address"] == "1 Khreshchatyk St, Kyiv"

    ticket = Ticket.query.get(data["id"])
    assert ticket.customer_lat == 50.45
    assert ticket.customer_lng == 30.52


def test_missing_address_skips_geocoding(client, monkeypatch):
    import routes

    def _should_not_be_called(address):
        raise AssertionError("geocode_address should not be called without an address")

    monkeypatch.setattr(routes, "geocode_address", _should_not_be_called)

    resp = client.post(
        "/tickets", json={"title": "Leaky tap", "customer_email": "customer@example.com"}
    )

    assert resp.status_code == 201
