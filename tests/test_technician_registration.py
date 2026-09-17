"""POST /technicians - location/service-radius fields for distance-aware
matching. geocode_address is monkeypatched throughout so these tests never
make a real call to Nominatim.
"""
import routes
from models import Technician


def _register(client, **overrides):
    payload = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+380671234567",
        "specialty": "plumbing",
    }
    payload.update(overrides)
    return client.post("/technicians", json=payload)


def test_registration_without_location_skips_geocoding(client, monkeypatch):
    def _should_not_be_called(address):
        raise AssertionError("geocode_address should not be called without a location")

    monkeypatch.setattr(routes, "geocode_address", _should_not_be_called)

    resp = _register(client)

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["location_label"] is None
    assert data["service_radius_km"] is None


def test_location_without_radius_gets_default_radius(client, monkeypatch, ctx):
    monkeypatch.setattr(routes, "geocode_address", lambda address: (50.45, 30.52))

    resp = _register(client, location="Kyiv")

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["location_label"] == "Kyiv"
    assert data["service_radius_km"] == routes.DEFAULT_SERVICE_RADIUS_KM

    technician = Technician.query.filter_by(email="jane@example.com").first()
    assert technician.lat == 50.45
    assert technician.lng == 30.52


def test_explicit_radius_is_respected(client, monkeypatch, ctx):
    monkeypatch.setattr(routes, "geocode_address", lambda address: (50.45, 30.52))

    resp = _register(client, location="Kyiv", service_radius_km=40)

    assert resp.status_code == 201
    technician = Technician.query.filter_by(email="jane@example.com").first()
    assert technician.service_radius_km == 40


def test_radius_without_location_is_ignored(client, ctx):
    # No location given, so geocode_address must not even be called - left
    # unmocked here and would blow up on a real network call if it were.
    resp = _register(client, service_radius_km=15)

    assert resp.status_code == 201
    technician = Technician.query.filter_by(email="jane@example.com").first()
    assert technician.service_radius_km is None
    assert technician.location_label is None


def test_invalid_radius_returns_400(client):
    resp = _register(client, location="Kyiv", service_radius_km="not-a-number")
    assert resp.status_code == 400


def test_negative_radius_returns_400(client):
    resp = _register(client, location="Kyiv", service_radius_km=-5)
    assert resp.status_code == 400


def test_zero_radius_returns_400(client):
    resp = _register(client, location="Kyiv", service_radius_km=0)
    assert resp.status_code == 400
