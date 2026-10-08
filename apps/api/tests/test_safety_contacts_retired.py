"""Supervisor Safety Contacts is retired: no endpoint or permission remains, even
for a user holding every Safety permission. Its tables are kept
(test_safety_contacts_database.py)."""

import pytest
from fastapi.testclient import TestClient

from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.main import create_app


def test_no_route_serves_supervisor_safety_contacts() -> None:
    paths = [getattr(route, "path", "") for route in create_app().routes]
    assert not [path for path in paths if "contact" in path]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/safety/contacts"),
        ("POST", "/api/v1/safety/contacts"),
        ("GET", "/api/v1/safety/contacts/supervisors"),
        ("GET", "/api/v1/safety/contacts/summary?year=2026"),
        ("GET", "/api/v1/safety/contacts/dashboard?year=2026"),
    ],
)
def test_retired_endpoints_are_not_found(method: str, path: str) -> None:
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: UserPrincipal(
        "tester", authenticated=True, granted=frozenset({Permission.SAFETY_MANAGE})
    )
    with TestClient(app) as client:
        assert client.request(method, path).status_code == 404


def test_contact_permissions_are_removed() -> None:
    assert not [p for p in Permission if ".contacts." in p]
