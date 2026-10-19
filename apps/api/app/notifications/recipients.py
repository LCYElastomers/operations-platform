"""Resolve workflow recipient rules into TO/CC/BCC address lists."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User, UserRole
from app.notifications.models import WorkflowRecipientRule

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str | None
    kind: str  # to | cc | bcc


def _normalize(email: str) -> str | None:
    value = email.strip().lower()
    return value if EMAIL_RE.match(value) else None


def _add(
    buckets: dict[str, dict[str, Recipient]],
    kind: str,
    email: str | None,
    name: str | None,
) -> None:
    if not email:
        return
    normalized = _normalize(email)
    if normalized is None:
        return
    # First kind wins for dedupe across TO/CC/BCC (prefer TO).
    for existing in buckets.values():
        if normalized in existing:
            return
    buckets[kind][normalized] = Recipient(email=normalized, name=name, kind=kind)


def resolve_recipients(
    session: Session,
    rules: list[WorkflowRecipientRule],
    *,
    payload: dict[str, Any],
) -> tuple[list[Recipient], list[Recipient], list[Recipient]]:
    buckets: dict[str, dict[str, Recipient]] = {"to": {}, "cc": {}, "bcc": {}}
    for rule in sorted(rules, key=lambda r: r.display_order):
        if not rule.active:
            continue
        kind = rule.recipient_type
        config = rule.strategy_config_json or {}
        strategy = rule.strategy_code
        if strategy == "assigned_external_email":
            _add(
                buckets,
                kind,
                payload.get("owner_email") or payload.get("assigned_email"),
                payload.get("owner_name") or payload.get("assigned_name"),
            )
        elif strategy == "entity_owner":
            _add(
                buckets,
                kind,
                payload.get("owner_email"),
                payload.get("owner_name"),
            )
        elif strategy == "entity_creator":
            _add(
                buckets,
                kind,
                payload.get("creator_email"),
                payload.get("creator_name"),
            )
        elif strategy == "assigned_user":
            user_id = payload.get("owner_user_id") or payload.get("assigned_user_id")
            if user_id:
                user = session.get(User, uuid.UUID(str(user_id)))
                if user is not None and user.status == "active":
                    _add(buckets, kind, user.email, user.name)
        elif strategy == "specific_user":
            user_id = config.get("user_id")
            if user_id:
                user = session.get(User, uuid.UUID(str(user_id)))
                if user is not None and user.status == "active":
                    _add(buckets, kind, user.email, user.name)
        elif strategy == "specific_role":
            role_code = config.get("role_code")
            if role_code:
                rows = session.execute(
                    select(User.email, User.name)
                    .join(UserRole, UserRole.user_id == User.id)
                    .where(
                        UserRole.role_code == role_code,
                        User.status == "active",
                    )
                ).all()
                for email, name in rows:
                    _add(buckets, kind, email, name)
        elif strategy == "department":
            # Platform has no org-wide departments yet; payload may supply a list.
            for entry in config.get("emails") or payload.get("department_emails") or []:
                if isinstance(entry, str):
                    _add(buckets, kind, entry, None)
                elif isinstance(entry, dict):
                    _add(buckets, kind, entry.get("email"), entry.get("name"))
        elif strategy == "distribution_group":
            for entry in config.get("emails") or []:
                if isinstance(entry, str):
                    _add(buckets, kind, entry, None)
                elif isinstance(entry, dict):
                    _add(buckets, kind, entry.get("email"), entry.get("name"))
        elif strategy == "custom_email":
            _add(buckets, kind, config.get("email"), config.get("name"))
    return (
        list(buckets["to"].values()),
        list(buckets["cc"].values()),
        list(buckets["bcc"].values()),
    )


def as_json(recipients: list[Recipient]) -> list[dict[str, str | None]]:
    return [{"email": r.email, "name": r.name} for r in recipients]
