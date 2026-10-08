"""Individual Incident and Near Miss records (migration 0009).

A record documents one event: its number, date, description, area and
classification. Records sit beside the monthly totals and never change them:
the monthly Incident and Near Miss totals stay authoritative, and the two are
compared only to show reconciliation warnings.

The reporting year and month are derived from ``incident_date`` and never
stored separately. Records are never deleted: a mistaken record is voided,
and a record whose type was wrong is reclassified, pointing at its active
replacement. Every change is audited (core.audit_events) and guarded by
``version`` (optimistic concurrency).
"""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.safety.models import SAFETY_SCHEMA, Area, MetricCategory

EVENT_TYPES = ("incident", "near_miss")
RECORD_STATUSES = ("active", "voided", "reclassified")
RECORD_SOURCES = ("manual", "legacy_import")
EARLIEST_INCIDENT_DATE = dt.date(2000, 1, 1)
MAX_DESCRIPTION_LENGTH = 4000
MAX_INCIDENT_NUMBER_LENGTH = 40
MAX_REASON_LENGTH = 1000
MAX_SOURCE_REFERENCE_LENGTH = 500
NUMBER_INDEX = "uq_incident_records_incident_number"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class IncidentRecord(Base):
    __tablename__ = "incident_records"
    __table_args__ = (
        CheckConstraint(_in("event_type", EVENT_TYPES), name="event_type"),
        CheckConstraint(_in("status", RECORD_STATUSES), name="status"),
        CheckConstraint(_in("source", RECORD_SOURCES), name="source"),
        CheckConstraint(
            f"incident_date BETWEEN DATE '{EARLIEST_INCIDENT_DATE.isoformat()}' "
            "AND DATE '2100-12-31'",
            name="incident_date",
        ),
        CheckConstraint(
            f"btrim(description) <> '' AND char_length(description) <= {MAX_DESCRIPTION_LENGTH}",
            name="description",
        ),
        # Stored in normalized form only (e.g. LCY-2026-037).
        CheckConstraint(
            "incident_number IS NULL OR incident_number ~ '^[A-Z]{2,10}-[0-9]{4}-[0-9]{3,6}$'",
            name="incident_number",
        ),
        CheckConstraint(
            f"status_reason IS NULL OR (btrim(status_reason) <> '' "
            f"AND char_length(status_reason) <= {MAX_REASON_LENGTH})",
            name="status_reason",
        ),
        CheckConstraint(
            "status = 'active' OR status_reason IS NOT NULL", name="inactive_has_reason"
        ),
        CheckConstraint(
            "status <> 'reclassified' OR related_incident_id IS NOT NULL",
            name="reclassified_has_replacement",
        ),
        CheckConstraint(
            "related_incident_id IS NULL OR related_incident_id <> id", name="related_not_self"
        ),
        CheckConstraint(
            f"source_reference IS NULL OR char_length(source_reference) "
            f"<= {MAX_SOURCE_REFERENCE_LENGTH}",
            name="source_reference",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            NUMBER_INDEX,
            "incident_number",
            unique=True,
            postgresql_where=text("incident_number IS NOT NULL"),
        ),
        Index("ix_incident_records_incident_date", "incident_date"),
        Index("ix_incident_records_event_type_date", "event_type", "incident_date"),
        Index("ix_incident_records_area_date", "area_id", "incident_date"),
        Index(
            "ix_incident_records_active_type_date",
            "event_type",
            "incident_date",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_incident_records_related_incident_id", "related_incident_id"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_number: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    incident_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    area_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(Area.id, name="fk_incident_records_area", ondelete="RESTRICT")
    )
    # An Incident Classification category (section incident_classification).
    classification_category_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            MetricCategory.id, name="fk_incident_records_classification", ondelete="RESTRICT"
        ),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    status_reason: Mapped[str | None] = mapped_column(Text)
    # For a reclassified record: its replacement.
    related_incident_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "safety.incident_records.id", name="fk_incident_records_related", ondelete="RESTRICT"
        ),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    # For an imported record: the import mapping and passage it came from. Not
    # returned by the public API.
    source_reference: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
