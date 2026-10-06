"""Writes platform audit events (core.audit_events)."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent

AuditAction = Literal["create", "update", "delete"]


@dataclass(frozen=True)
class AuditChange:
    action: AuditAction
    entity_type: str
    entity_key: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None


def record_changes(
    session: Session,
    *,
    actor_id: str,
    change_set_id: uuid.UUID,
    occurred_at: dt.datetime,
    changes: Sequence[AuditChange],
) -> None:
    """Add audit rows to the caller's transaction, so they commit with the change."""
    if not changes:
        return
    session.execute(
        insert(AuditEvent),
        [
            {
                "occurred_at": occurred_at,
                "actor_id": actor_id,
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
