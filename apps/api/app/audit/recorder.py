"""Writes platform audit events (core.audit_events)."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth.models import User

AuditAction = Literal["create", "update", "delete"]


@dataclass(frozen=True)
class AuditChange:
    action: AuditAction
    entity_type: str
    entity_key: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None


def _user_id(actor_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(actor_id)
    except ValueError:
        return None


def record_changes(
    session: Session,
    *,
    actor_id: str,
    change_set_id: uuid.UUID,
    occurred_at: dt.datetime,
    changes: Sequence[AuditChange],
) -> None:
    """Add audit rows to the caller's transaction, so they commit with the change.

    ``actor_id`` is a platform user's ID (from the session, never the request
    body) or a system actor such as ``legacy-import``. For users the event also
    links the user and keeps their display name as it was at the time.
    """
    if not changes:
        return
    user_id = _user_id(actor_id)
    actor_name = (
        session.execute(select(User.name).where(User.id == user_id)).scalar_one_or_none()
        if user_id is not None
        else None
    )
    if actor_name is None:
        user_id = None
    session.execute(
        insert(AuditEvent),
        [
            {
                "occurred_at": occurred_at,
                "actor_id": actor_id,
                "actor_user_id": user_id,
                "actor_name": actor_name,
                "change_set_id": change_set_id,
                "action": change.action,
                "entity_type": change.entity_type,
                "entity_key": change.entity_key,
                "old_value": change.old_value,
                "new_value": change.new_value,
            }
            for change in changes
        ],
    )
