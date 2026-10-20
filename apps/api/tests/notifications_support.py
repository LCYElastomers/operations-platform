"""Shared fixtures for the Notifications tests: the route/permission matrix and
fixture-only identities. Nothing here is production data or a real credential."""

from __future__ import annotations

from typing import Any

from app.core.permissions import Permission

P = Permission

BASE = "/api/v1/admin/notifications"

# Fixture-only secret. It must never appear in any response, log, row or audit event.
SECRET = "re_FIXTURE_notifications_secret_0123456789"  # noqa: S105

NOTIFICATION_PERMISSIONS = {p for p in Permission if p.value.startswith("notifications.")}

ID = "00000000-0000-4000-8000-0000000000aa"

# (method, path under BASE, the one permission that opens it, a valid request body)
ROUTES: list[tuple[str, str, Permission, dict[str, Any] | None]] = [
    ("GET", "/overview", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/event-types", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/templates", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/templates/{template_id}", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/templates/{template_id}/revisions/{revision_id}", P.NOTIFICATIONS_VIEW, None),
    ("POST", "/templates/{template_id}/draft", P.NOTIFICATIONS_TEMPLATES_MANAGE, None),
    (
        "PATCH",
        "/templates/{template_id}/revisions/{revision_id}",
        P.NOTIFICATIONS_TEMPLATES_MANAGE,
        {"subjectTemplate": "s"},
    ),
    (
        "POST",
        "/templates/{template_id}/revisions/{revision_id}/validate",
        P.NOTIFICATIONS_VIEW,
        {"eventTypeCode": "psm.action.assigned"},
    ),
    (
        "POST",
        "/templates/{template_id}/revisions/{revision_id}/preview",
        P.NOTIFICATIONS_VIEW,
        {"eventTypeCode": "psm.action.assigned"},
    ),
    (
        "POST",
        "/templates/{template_id}/revisions/{revision_id}/publish",
        P.NOTIFICATIONS_TEMPLATES_MANAGE,
        {"eventTypeCode": "psm.action.assigned"},
    ),
    ("GET", "/workflows", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/workflows/{workflow_id}", P.NOTIFICATIONS_VIEW, None),
    ("PATCH", "/workflows/{workflow_id}", P.NOTIFICATIONS_WORKFLOWS_MANAGE, {"enabled": False}),
    ("GET", "/deliveries", P.NOTIFICATIONS_DELIVERY_VIEW, None),
    ("GET", "/deliveries/{delivery_id}", P.NOTIFICATIONS_DELIVERY_VIEW, None),
    ("POST", "/deliveries/{delivery_id}/retry", P.NOTIFICATIONS_DELIVERY_RETRY, None),
    ("GET", "/test/psm-actions", P.NOTIFICATIONS_TEST_SEND, None),
    ("POST", "/test/preview", P.NOTIFICATIONS_TEST_SEND, {"templateId": 1}),
    (
        "POST",
        "/test/send",
        P.NOTIFICATIONS_TEST_SEND,
        {"templateId": 1, "toEmail": "someone@fixture.test"},
    ),
    ("GET", "/settings", P.NOTIFICATIONS_VIEW, None),
    ("PATCH", "/settings", P.NOTIFICATIONS_SETTINGS_MANAGE, {"emergencyPause": True}),
]


def url(template: str) -> str:
    """The full URL of a route template, with ids that exist nowhere (so a request that
    passes authorization ends in a 404 or 422, never in data)."""
    return BASE + template.format(template_id=999_001, revision_id=999_001, workflow_id=999_001, delivery_id=ID)
