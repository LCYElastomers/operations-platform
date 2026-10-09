import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CORE_SCHEMA = "core"

AUDIT_ACTIONS = ("create", "update", "delete")


class AuditEvent(Base):
    """Platform audit trail of user data changes: who changed what, from what, to what, when.

    One row per changed entity. ``change_set_id`` groups the rows written by
    one save. ``old_value`` is NULL for a create and ``new_value`` is NULL for
    a delete. Values hold business data only, never credentials or secrets.
    Rows are written in the same transaction as the change they describe.
    Besides record changes, user, role and sign-in administration is audited
    here (entity types ``core.user``, ``core.role``).
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("action IN ('create', 'update', 'delete')", name="action"),
        {"schema": CORE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # The acting user's ID as text, or a system actor such as "legacy-import".
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    # The platform user, when the actor is one (null for system and pre-login actors).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.users.id", name="fk_audit_events_actor_user", ondelete="RESTRICT")
    )
    # The actor's display name when the event was written; history keeps it if the name changes.
    actor_name: Mapped[str | None] = mapped_column(Text)
    change_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    # Dotted module-qualified type, e.g. "safety.monthly_metric_value".
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Stable, human-readable identity of the entity within its type.
    entity_key: Mapped[str] = mapped_column(Text, nullable=False)
    # none_as_null: store SQL NULL, not the JSON literal null, so "IS NULL" finds creates/deletes.
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))


Index(
    "ix_audit_events_entity",
    AuditEvent.entity_type,
    AuditEvent.entity_key,
    AuditEvent.occurred_at.desc(),
)
Index("ix_audit_events_occurred_at_desc", AuditEvent.occurred_at.desc())
