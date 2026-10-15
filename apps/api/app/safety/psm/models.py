"""Process Safety Management storage (migration 0015), in the ``safety`` schema.

A PHA study holds recommendations; a recommendation holds one or more hazard
scenarios and at most one linked action. Scenarios are rows of their own, never
copies of the recommendation. Governing risk, overdue and aging are derived
from these rows when read and never stored.

Managed records are archived, not deleted; every change is audited in
``core.audit_events`` and guarded by ``version``. Imported rows keep their
source key, rows and the workbook's cell text (``source_cells``).
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, user_link
from app.safety.models import SAFETY_SCHEMA, Area
from app.safety.psm.reference import (
    ACTION_STATUSES,
    DISPOSITIONS,
    EVIDENCE_TYPES,
    MAX_SHORT,
    MAX_TEXT,
    NOTIFICATION_EVENTS,
    NOTIFICATION_STATUSES,
    RISKS,
    STUDY_STATUSES,
    UPDATE_TYPES,
)

NAME_KEY_SQL = "lower(regexp_replace(btrim(name), '\\s+', ' ', 'g'))"
EMAIL_PATTERN = "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"


def _in(column: str, values: Any) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _text(column: str, length: int, *, optional: bool = False) -> str:
    rule = f"btrim({column}) <> '' AND char_length({column}) <= {length}"
    return f"{column} IS NULL OR ({rule})" if optional else rule


def _created() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PsmStudyType(Base):
    __tablename__ = "psm_study_types"
    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint("code ~ '^[a-z0-9_]{1,50}$'", name="code"),
        CheckConstraint(_text("name", 100), name="name"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = _created()


class _NamedReference:
    """Reference rows identified by a name. ``name_key`` (the name in lower case
    with spaces collapsed) is unique, so near-duplicates such as "Operations"
    and "operations " cannot both exist. Inactive rows stay on the records that
    use them."""

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_key: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[dt.datetime] = _created()
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = _created()
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class PsmDepartment(_NamedReference, Base):
    __tablename__ = "psm_departments"
    __table_args__ = (
        UniqueConstraint("name_key"),
        CheckConstraint(_text("name", MAX_SHORT), name="name"),
        CheckConstraint(f"name_key = {NAME_KEY_SQL}", name="name_key"),
        {"schema": SAFETY_SCHEMA},
    )


class PsmProcessNode(_NamedReference, Base):
    """A PHA node as written, e.g. "10. 1st Stripper V-7406"."""

    __tablename__ = "psm_process_nodes"
    __table_args__ = (
        UniqueConstraint("name_key"),
        CheckConstraint(_text("name", 1000), name="name"),
        CheckConstraint(f"name_key = {NAME_KEY_SQL}", name="name_key"),
        {"schema": SAFETY_SCHEMA},
    )


class PsmElement(Base):
    """OSHA 1910.119 PSM elements, for audits."""

    __tablename__ = "psm_elements"
    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint("code ~ '^[a-z0-9_]{1,50}$'", name="code"),
        CheckConstraint(_text("name", MAX_SHORT), name="name"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    regulation: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class PsmStudy(Base):
    __tablename__ = "psm_studies"
    __table_args__ = (
        UniqueConstraint("study_code"),
        UniqueConstraint("recommendation_prefix"),
        CheckConstraint("study_code ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$'", name="study_code"),
        CheckConstraint(
            "recommendation_prefix ~ '^[A-Z0-9][A-Z0-9-]{0,29}$'", name="recommendation_prefix"
        ),
        CheckConstraint(_text("title", MAX_SHORT), name="title"),
        CheckConstraint("year BETWEEN 1990 AND 2100", name="year"),
        CheckConstraint(_in("status", STUDY_STATUSES), name="status"),
        CheckConstraint(_text("description", MAX_TEXT, optional=True), name="description"),
        CheckConstraint(
            "source_key IS NULL OR (btrim(source_key) <> '' AND char_length(source_key) <= 300)",
            name="source_key",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "uq_psm_studies_source_key",
            "source_key",
            unique=True,
            postgresql_where=text("source_key IS NOT NULL"),
        ),
        Index("ix_psm_studies_year", "year"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    study_code: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    study_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(PsmStudyType.id, ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    # Prefix of the recommendations' display IDs, e.g. "PHA-2026" -> PHA-2026-001.
    recommendation_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    # Null unless the source records a study date; never inferred.
    study_date: Mapped[dt.date | None] = mapped_column(Date)
    source_file_name: Mapped[str | None] = mapped_column(Text)
    source_sheet_name: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(Text)
    source_key: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[dt.datetime] = _created()
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = _created()
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PsmStudyArea(Base):
    """The plant areas a study covers (``safety.areas``)."""

    __tablename__ = "psm_study_areas"
    __table_args__ = (
        PrimaryKeyConstraint("study_id", "area_id"),
        Index("ix_psm_study_areas_area_id", "area_id"),
        {"schema": SAFETY_SCHEMA},
    )

    study_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(PsmStudy.id, ondelete="CASCADE"), nullable=False
    )
    area_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Area.id, ondelete="RESTRICT"), nullable=False
    )


class PsmRecommendation(Base):
    __tablename__ = "psm_recommendations"
    __table_args__ = (
        UniqueConstraint("study_id", "recommendation_number"),
        UniqueConstraint("display_id"),
        CheckConstraint("recommendation_number BETWEEN 1 AND 9999", name="recommendation_number"),
        CheckConstraint(_text("area_equipment", MAX_SHORT), name="area_equipment"),
        CheckConstraint(_text("recommendation_text", MAX_TEXT), name="recommendation_text"),
        CheckConstraint(_in("disposition", DISPOSITIONS), name="disposition"),
        CheckConstraint(
            "disposition <> 'rejected' OR disposition_justification IS NOT NULL",
            name="rejected_has_justification",
        ),
        CheckConstraint(
            "disposition = 'pending_review' OR disposition_at IS NOT NULL",
            name="decided_has_time",
        ),
        CheckConstraint(
            _text("disposition_justification", MAX_TEXT, optional=True),
            name="disposition_justification",
        ),
        CheckConstraint(_text("notes", MAX_TEXT, optional=True), name="notes"),
        CheckConstraint("(archived_at IS NULL) = (archive_reason IS NULL)", name="archive_reason"),
        CheckConstraint(
            "source_key IS NULL OR (btrim(source_key) <> '' AND char_length(source_key) <= 300)",
            name="source_key",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "uq_psm_recommendations_source_key",
            "source_key",
            unique=True,
            postgresql_where=text("source_key IS NOT NULL"),
        ),
        Index("ix_psm_recommendations_disposition", "disposition"),
        Index("ix_psm_recommendations_process_node_id", "process_node_id"),
        Index("ix_psm_recommendations_archived_at", "archived_at"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    study_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(PsmStudy.id, ondelete="RESTRICT"), nullable=False
    )
    recommendation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_id: Mapped[str] = mapped_column(Text, nullable=False)
    area_equipment: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    process_node_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(PsmProcessNode.id, ondelete="RESTRICT")
    )
    disposition: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending_review'")
    )
    disposition_justification: Mapped[str | None] = mapped_column(Text)
    disposition_by_user_id: Mapped[uuid.UUID | None] = user_link()
    disposition_by_name: Mapped[str | None] = mapped_column(Text)
    disposition_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    # Saved without scenarios on purpose; left out of official figures.
    is_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source_row_start: Mapped[int | None] = mapped_column(Integer)
    source_row_end: Mapped[int | None] = mapped_column(Integer)
    source_key: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[dt.datetime] = _created()
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = _created()
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[str | None] = mapped_column(Text)
    archive_reason: Mapped[str | None] = mapped_column(Text)


class PsmScenario(Base):
    """One hazard scenario of a recommendation, in workbook order."""

    __tablename__ = "psm_scenarios"
    __table_args__ = (
        # Deferred so scenarios can be reordered in one transaction.
        UniqueConstraint(
            "recommendation_id", "sequence_number", deferrable=True, initially="DEFERRED"
        ),
        CheckConstraint("sequence_number BETWEEN 1 AND 999", name="sequence_number"),
        CheckConstraint(_text("event", MAX_TEXT), name="event"),
        CheckConstraint(_text("cause", MAX_TEXT), name="cause"),
        CheckConstraint(_text("consequence", MAX_TEXT), name="consequence"),
        CheckConstraint(_in("risk", RISKS), name="risk"),
        CheckConstraint(_text("area_equipment", MAX_SHORT, optional=True), name="area_equipment"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_psm_scenarios_risk", "risk"),
        Index("ix_psm_scenarios_process_node_id", "process_node_id"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(PsmRecommendation.id, ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    cause: Mapped[str] = mapped_column(Text, nullable=False)
    consequence: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(Text, nullable=False)
    # The risk cell exactly as the workbook wrote it (imported rows only).
    risk_source: Mapped[str | None] = mapped_column(Text)
    # The scenario's own equipment and node. Imported rows: as written on the row,
    # or inherited from the recommendation (equipment) or the row above (node).
    area_equipment: Mapped[str | None] = mapped_column(Text)
    process_node_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(PsmProcessNode.id, ondelete="RESTRICT")
    )
    source_row: Mapped[int | None] = mapped_column(Integer)
    # Imported rows: every source cell of the row, verbatim ({"A2": ..., "B2": ...}).
    source_cells: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[dt.datetime] = _created()
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = _created()
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class PsmAction(Base):
    """The primary action generated when a recommendation is accepted."""

    __tablename__ = "psm_actions"
    __table_args__ = (
        # One primary action per recommendation.
        UniqueConstraint("recommendation_id"),
        UniqueConstraint("action_number"),
        CheckConstraint("action_number ~ '^PSM-ACT-[0-9]{4}-[0-9]{3,6}$'", name="action_number"),
        CheckConstraint(_text("title", 500), name="title"),
        CheckConstraint(_text("description", MAX_TEXT, optional=True), name="description"),
        CheckConstraint(_text("owner_name", MAX_SHORT, optional=True), name="owner_name"),
        CheckConstraint(
            f"owner_email IS NULL OR (owner_email = lower(btrim(owner_email)) "
            f"AND char_length(owner_email) <= 254 AND owner_email ~ '{EMAIL_PATTERN}')",
            name="owner_email",
        ),
        CheckConstraint(_in("status", ACTION_STATUSES), name="status"),
        CheckConstraint(
            "status NOT IN ('pending_verification', 'closed') "
            "OR (closure_summary IS NOT NULL AND closure_requested_at IS NOT NULL)",
            name="closure_requested",
        ),
        CheckConstraint(
            "status <> 'closed' OR (closed_at IS NOT NULL AND verified_at IS NOT NULL "
            "AND verified_by IS NOT NULL)",
            name="closed_is_verified",
        ),
        CheckConstraint("status = 'closed' OR closed_at IS NULL", name="closed_at"),
        CheckConstraint("(archived_at IS NULL) = (archive_reason IS NULL)", name="archive_reason"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_psm_actions_status", "status"),
        Index("ix_psm_actions_due_date", "due_date"),
        Index("ix_psm_actions_department_id", "department_id"),
        Index("ix_psm_actions_owner_name", "owner_name"),
        Index("ix_psm_actions_archived_at", "archived_at"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(PsmRecommendation.id, ondelete="RESTRICT"), nullable=False
    )
    action_number: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # The task: what is to be done.
    description: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(PsmDepartment.id, ondelete="RESTRICT")
    )
    # Owners need no platform account: a user, or a recorded name and email.
    owner_user_id: Mapped[uuid.UUID | None] = user_link()
    owner_name: Mapped[str | None] = mapped_column(Text)
    owner_email: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'not_started'"))
    closure_summary: Mapped[str | None] = mapped_column(Text)
    # Set when closure was requested without evidence under a documented exception.
    closure_exception_reason: Mapped[str | None] = mapped_column(Text)
    closure_requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    closure_requested_by: Mapped[str | None] = mapped_column(Text)
    closure_requested_by_name: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(Text)
    verified_by_name: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    return_reason: Mapped[str | None] = mapped_column(Text)
    reopened_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reopen_reason: Mapped[str | None] = mapped_column(Text)
    # The recommendation was rejected after this action was generated; an
    # administrator decides what happens to it. Nothing is deleted.
    requires_resolution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[dt.datetime] = _created()
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = _created()
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[str | None] = mapped_column(Text)
    archive_reason: Mapped[str | None] = mapped_column(Text)


class PsmActionUpdate(Base):
    """An update or comment on an action; status moves are recorded here too."""

    __tablename__ = "psm_action_updates"
    __table_args__ = (
        CheckConstraint(_in("update_type", UPDATE_TYPES), name="update_type"),
        CheckConstraint(_text("body", MAX_TEXT), name="body"),
        CheckConstraint(
            f"previous_status IS NULL OR {_in('previous_status', ACTION_STATUSES)}",
            name="previous_status",
        ),
        CheckConstraint(
            f"new_status IS NULL OR {_in('new_status', ACTION_STATUSES)}", name="new_status"
        ),
        Index("ix_psm_action_updates_action_id", "action_id", "created_at"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    action_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(PsmAction.id, ondelete="RESTRICT"), nullable=False
    )
    update_type: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    previous_status: Mapped[str | None] = mapped_column(Text)
    new_status: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = user_link()
    created_by_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = _created()


class PsmAttachment(Base):
    """Evidence on a recommendation or its action. Removal is recorded, not deleted."""

    __tablename__ = "psm_attachments"
    __table_args__ = (
        CheckConstraint("(recommendation_id IS NULL) <> (action_id IS NULL)", name="one_parent"),
        CheckConstraint(_in("evidence_type", EVIDENCE_TYPES), name="evidence_type"),
        CheckConstraint(_text("original_file_name", 255), name="original_file_name"),
        CheckConstraint(_text("description", 1000, optional=True), name="description"),
        CheckConstraint("size_bytes > 0", name="size_bytes"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        CheckConstraint("(removed_at IS NULL) = (removal_reason IS NULL)", name="removal_reason"),
        Index("ix_psm_attachments_recommendation_id", "recommendation_id"),
        Index("ix_psm_attachments_action_id", "action_id"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recommendation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey(PsmRecommendation.id, ondelete="RESTRICT")
    )
    action_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey(PsmAction.id, ondelete="RESTRICT")
    )
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    original_file_name: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = user_link()
    uploaded_by_name: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[dt.datetime] = _created()
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[str | None] = mapped_column(Text)
    removed_by_name: Mapped[str | None] = mapped_column(Text)
    removal_reason: Mapped[str | None] = mapped_column(Text)


class PsmAttachmentContent(Base):
    """The file bytes, kept apart so lists never load them."""

    __tablename__ = "psm_attachment_contents"
    __table_args__ = ({"schema": SAFETY_SCHEMA},)

    attachment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(PsmAttachment.id, ondelete="RESTRICT"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class PsmNotification(Base):
    """An email the platform owes about an action (the outbox).

    ``queued`` until a delivery attempt; ``sent`` only when the mail server
    accepted it; ``failed`` with the error otherwise; ``skipped`` when there was
    nobody to send to or the setting is off. Reminders carry a ``dedupe_key`` so
    each is queued once.
    """

    __tablename__ = "psm_notifications"
    __table_args__ = (
        CheckConstraint(_in("event_type", NOTIFICATION_EVENTS), name="event_type"),
        CheckConstraint(_in("status", NOTIFICATION_STATUSES), name="status"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("status <> 'sent' OR sent_at IS NOT NULL", name="sent_at"),
        Index(
            "uq_psm_notifications_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
        Index("ix_psm_notifications_status", "status"),
        Index("ix_psm_notifications_action_id", "action_id"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    action_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(PsmAction.id, ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(Text)
    recipient_email: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    status_detail: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()
    last_attempt_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PsmNotificationSettings(Base):
    """The one row of PSM notification settings."""

    __tablename__ = "psm_notification_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("due_soon_days BETWEEN 1 AND 90", name="due_soon_days"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    notify_on_assignment: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notify_on_due_date_change: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notify_on_status_change: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notify_on_comment: Mapped[bool] = mapped_column(Boolean, nullable=False)
    due_soon_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False)
    overdue_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False)
    due_soon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    updated_at: Mapped[dt.datetime] = _created()
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
