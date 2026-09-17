"""geocoding.geocode_address()/haversine_km() - requests.get is mocked
throughout, so these tests never make a real call to Nominatim.
"""
import requests

import geocoding


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json_data


def test_empty_address_returns_none_without_network_call(monkeypatch):
    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("requests.get should not be called for an empty address")

    monkeypatch.setattr(geocoding.requests, "get", _should_not_be_called)

    assert geocoding.geocode_address("") == (None, None)
    assert geocoding.geocode_address(None) == (None, None)
    assert geocoding.geocode_address("   ") == (None, None)


def test_successful_geocode_returns_lat_lng(monkeypatch):
    monkeypatch.setattr(
        geocoding.requests, "get",
        lambda *a, **k: _FakeResponse([{"lat": "50.4501", "lon": "30.5234"}]),
    )

    lat, lng = geocoding.geocode_address("Kyiv, Ukraine")

    assert lat == 50.4501
    assert lng == 30.5234


def test_no_results_returns_none(monkeypatch):
    monkeypatch.setattr(geocoding.requests, "get", lambda *a, **k: _FakeResponse([]))

    assert geocoding.geocode_address("nonexistent place xyz123") == (None, None)


def test_request_exception_returns_none_instead_of_raising(monkeypatch):
    def _raise(*a, **k):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(geocoding.requests, "get", _raise)

    assert geocoding.geocode_address("somewhere") == (None, None)


def test_malformed_result_returns_none(monkeypatch):
    monkeypatch.setattr(
        geocoding.requests, "get",
        lambda *a, **k: _FakeResponse([{"unexpected": "shape"}]),
    )

    assert geocoding.geocode_address("somewhere") == (None, None)


def test_user_agent_header_is_sent(monkeypatch):
    captured = {}

    def _fake_get(url, params, headers, timeout):
        captured["headers"] = headers
        return _FakeResponse([{"lat": "1.0", "lon": "2.0"}])

    monkeypatch.setattr(geocoding.requests, "get", _fake_get)
    geocoding.geocode_address("somewhere")

    assert "User-Agent" in captured["headers"]


def test_haversine_zero_distance_for_same_point():
    assert geocoding.haversine_km(50.0, 30.0, 50.0, 30.0) == 0


def test_haversine_known_distance_kyiv_to_lviv():
    # ~470 km great-circle distance between the two cities.
    distance = geocoding.haversine_km(50.4501, 30.5234, 49.8397, 24.0297)
    assert 460 <= distance <= 480
