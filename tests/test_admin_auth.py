"""Admin/mutating endpoints must reject requests without the correct
credential - X-Admin-Token for JSON endpoints, HTTP Basic Auth for the
browser-viewed dashboard.
"""
import base64

import pytest

from tests.conftest import ADMIN_TOKEN


@pytest.mark.parametrize(
    "method,path",
    [
        ("patch", "/technicians/1/availability"),
        ("delete", "/tickets/1"),
        ("delete", "/technicians/1"),
        ("post", "/admin/reassign-pending"),
        ("patch", "/tickets/1"),
    ],
)
def test_protected_endpoints_reject_without_token(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401


def test_protected_endpoint_accepts_correct_token(client, admin_headers):
    resp = client.delete("/tickets/999999", headers=admin_headers)
    # Auth passed through to the real handler - 404 (no such ticket), not 401.
    assert resp.status_code == 404


def test_dashboard_requires_basic_auth(client):
    resp = client.get("/dashboard/view")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("WWW-Authenticate", "")


def test_dashboard_accepts_correct_basic_auth(client):
    creds = base64.b64encode(f"admin:{ADMIN_TOKEN}".encode()).decode()
    resp = client.get("/dashboard/view", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 200
