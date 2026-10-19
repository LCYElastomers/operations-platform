"""Build template context from a notification event payload."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.config import Settings


def nest(flat: dict[str, Any]) -> dict[str, Any]:
    """Turn ``{"action.title": "x"}`` into ``{"action": {"title": "x"}}``."""
    root: dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        node = root
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
    return root


def build_context(
    *,
    payload: dict[str, Any],
    settings: Settings,
    recipient_name: str | None,
    recipient_email: str | None,
    occurred_at: dt.datetime,
    entity_reference: str | None,
    entity_url: str | None,
) -> dict[str, Any]:
    base = settings.app_public_url.rstrip("/") if settings.app_public_url else ""
    flat = {
        "recipient.name": recipient_name or "",
        "recipient.email": recipient_email or "",
        "app.base_url": base,
        "event.occurred_at": occurred_at.isoformat(),
        "entity.reference": entity_reference or "",
        "entity.url": entity_url or "",
    }
    for key, value in payload.items():
        if key.startswith("_"):
            continue
        # Payload keys are already dotted (action.title) or nested.
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                flat[f"{key}.{child_key}"] = child_value
        else:
            flat[key] = value
    return nest(flat)
