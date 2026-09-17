import logging
import math

import requests

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy requires a real identifying User-Agent - requests
# without one get blocked outright.
USER_AGENT = "maintenance-ticket-router (contact: bogdanzvaric116@gmail.com)"
EARTH_RADIUS_KM = 6371.0


def geocode_address(address):
    """Best-effort geocoding of a free-text address via Nominatim
    (OpenStreetMap) - returns (lat, lng) floats, or (None, None) if the
    address is empty, the service errors/times out, or nothing matches.

    Never raises: geocoding only enables distance-aware technician
    matching, it's not a requirement for creating a ticket or registering
    a technician, so any failure here degrades to "no coordinates on file"
    rather than blocking the request.
    """
    address = (address or "").strip()
    if not address:
        return None, None

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=5,
        )
        response.raise_for_status()
        results = response.json()
    except (requests.RequestException, ValueError):
        logger.exception("Geocoding failed for address: %r", address)
        return None, None

    if not results:
        return None, None

    try:
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None, None


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km between two lat/lng points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
