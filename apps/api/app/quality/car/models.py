"""Corrective Action Report storage (migration 0012).

``Car`` holds one report, structured by the sections of the current form
(QMS-006-1 Rev. 2). A report may be saved incomplete: only its number, subject
and request date are required. Its corrective actions, Why-Why rows, approvals
and related-record links are child rows. Days open, past due, totals and
progress are derived (``app.quality.car.calculations``) and never stored.
Null is "not recorded", distinct from No, 0 or an empty list.

Reports are never deleted; every change is audited and guarded by ``version``.
Imported reports keep their original number, source file (``source_reference``)
and any older-form values without a current field (``legacy_fields``).
"""

import datetime as dt
from decimal import Decimal
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
    Numeric,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.quality.car.reference import (
    ACTION_STATUSES,
    APPROVAL_FUNCTIONS,
    CAR_NUMBER_PATTERN,
    CAR_STATUSES,
    EFFECTIVENESS_RESULTS,
    PRODUCTION_FIELDS,
    WHY_HEADER_TEXT_FIELDS,
)
from app.quality.cost.models import CostRecord
from app.quality.moisture.models import QUALITY_SCHEMA

CAR_SOURCES = ("manual", "legacy_import")
EARLIEST_CAR_DATE = dt.date(2000, 1, 1)
MAX_SHORT_LENGTH = 200
MAX_LONG_LENGTH = 8000
CODE_PATTERN = "^[a-z_]+$"
REFERENCE_TYPE_PATTERN = "^[a-z_]+$"
SOURCE_KEY_INDEX = "uq_cars_source_key"

# Optional single-line text columns of ``cars``.
SHORT_TEXT_FIELDS = (
    "requested_by",
    "assigned_to",
    "closure_approved_by",
    "previous_car",
    "containment_owner",
    "disposition_other",
    "incident_type",
    "equipment_involved",
    "work_order_number",
    "reviewer",
    "follow_up_reference",
    *PRODUCTION_FIELDS,
    *WHY_HEADER_TEXT_FIELDS,
)
# Optional multi-line text columns of ``cars``.
LONG_TEXT_FIELDS = (
    "nonconformity_description",
    "objective_evidence",
    "immediate_actions",
    "investigation_summary",
    "true_root_cause",
    "similar_nonconformities",
    "procedures_revised",
    "supporting_documents",
    "success_criteria",
    "effectiveness_evidence",
    "migration_notes",
)
CODE_FIELDS = ("source_code", "department_code", "root_cause_code")
MONEY_FIELDS = ("material_loss", "production_time_loss", "other_costs")


def _in(column: str, values: Any) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _optional_text(column: str, length: int) -> str:
    return f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {length})"


class Car(Base):
    __tablename__ = "cars"
    __table_args__ = (
        UniqueConstraint("car_number"),
        CheckConstraint(f"car_number ~ '{CAR_NUMBER_PATTERN}'", name="car_number"),
        CheckConstraint(
            f"btrim(subject) <> '' AND char_length(subject) <= {MAX_SHORT_LENGTH}", name="subject"
        ),
        CheckConstraint(
            f"request_date BETWEEN DATE '{EARLIEST_CAR_DATE.isoformat()}' AND DATE '2100-12-31'",
            name="request_date",
        ),
        # The older form records no status; only an imported report may lack one.
        CheckConstraint(f"status IS NULL OR {_in('status', CAR_STATUSES)}", name="status"),
        CheckConstraint("status IS NOT NULL OR source = 'legacy_import'", name="status_required"),
        CheckConstraint(
            "(status = 'closed') = (date_closed IS NOT NULL) "
            "OR (status IS NULL AND date_closed IS NULL)",
            name="closed_has_date",
        ),
        CheckConstraint(
            "date_closed IS NULL OR date_closed >= request_date", name="date_closed_after_request"
        ),
        CheckConstraint(
            f"effectiveness_result IS NULL OR {_in('effectiveness_result', EFFECTIVENESS_RESULTS)}",
            name="effectiveness_result",
        ),
        *(
            CheckConstraint(f"{column} IS NULL OR {column} ~ '{CODE_PATTERN}'", name=column)
            for column in CODE_FIELDS
        ),
        CheckConstraint(
            "array_position(disposition_codes, NULL) IS NULL "
            "AND array_to_string(disposition_codes, ',') ~ '^([a-z_]+(,[a-z_]+)*)?$'",
            name="disposition_codes",
        ),
        *(
            CheckConstraint(_optional_text(column, MAX_SHORT_LENGTH), name=column)
            for column in SHORT_TEXT_FIELDS
        ),
        *(
            CheckConstraint(_optional_text(column, MAX_LONG_LENGTH), name=column)
            for column in LONG_TEXT_FIELDS
        ),
        *(CheckConstraint(f"{column} >= 0", name=column) for column in MONEY_FIELDS),
        CheckConstraint(_in("source", CAR_SOURCES), name="source"),
        CheckConstraint(
            "source_key IS NULL OR (btrim(source_key) <> '' AND char_length(source_key) <= 200)",
            name="source_key",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            SOURCE_KEY_INDEX,
            "source_key",
            unique=True,
            postgresql_where=text("source_key IS NOT NULL"),
        ),
        # A Quality Cost record is linked to at most one CAR.
        Index(
            "uq_cars_quality_cost_record_id",
            "quality_cost_record_id",
            unique=True,
            postgresql_where=text("quality_cost_record_id IS NOT NULL"),
        ),
        Index("ix_cars_request_date", "request_date"),
        Index("ix_cars_status_due_date", "status", "due_date"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Identification.
    car_number: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str | None] = mapped_column(Text)
    request_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(Text)
    date_closed: Mapped[dt.date | None] = mapped_column(Date)
    closure_approved_by: Mapped[str | None] = mapped_column(Text)
    # 1 Nonconformity identification.
    source_code: Mapped[str | None] = mapped_column(Text)
    department_code: Mapped[str | None] = mapped_column(Text)
    started_on: Mapped[dt.date | None] = mapped_column(Date)
    started_time: Mapped[dt.time | None] = mapped_column(Time)
    ended_on: Mapped[dt.date | None] = mapped_column(Date)
    ended_time: Mapped[dt.time | None] = mapped_column(Time)
    previous_occurrence: Mapped[bool | None] = mapped_column(Boolean)
    previous_car: Mapped[str | None] = mapped_column(Text)
    nonconformity_description: Mapped[str | None] = mapped_column(Text)
    objective_evidence: Mapped[str | None] = mapped_column(Text)
    # 2 Immediate correction and containment.
    immediate_actions: Mapped[str | None] = mapped_column(Text)
    containment_owner: Mapped[str | None] = mapped_column(Text)
    containment_completed_on: Mapped[dt.date | None] = mapped_column(Date)
    disposition_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    disposition_other: Mapped[str | None] = mapped_column(Text)
    safety_hazard: Mapped[bool | None] = mapped_column(Boolean)
    environmental_hazard: Mapped[bool | None] = mapped_column(Boolean)
    customer_impact: Mapped[bool | None] = mapped_column(Boolean)
    # 3 Investigation and root cause.
    incident_type: Mapped[str | None] = mapped_column(Text)
    root_cause_code: Mapped[str | None] = mapped_column(Text)
    equipment_involved: Mapped[str | None] = mapped_column(Text)
    work_order_number: Mapped[str | None] = mapped_column(Text)
    investigation_summary: Mapped[str | None] = mapped_column(Text)
    true_root_cause: Mapped[str | None] = mapped_column(Text)
    # 4 Systemic evaluation.
    similar_nonconformities: Mapped[str | None] = mapped_column(Text)
    similar_issue_found: Mapped[bool | None] = mapped_column(Boolean)
    additional_action_required: Mapped[bool | None] = mapped_column(Boolean)
    # 5 Corrective action plan (the plan as a whole; actions are child rows).
    procedures_revised: Mapped[str | None] = mapped_column(Text)
    training_completed: Mapped[bool | None] = mapped_column(Boolean)
    supporting_documents: Mapped[str | None] = mapped_column(Text)
    plan_completed_on: Mapped[dt.date | None] = mapped_column(Date)
    # 6 Effectiveness review.
    success_criteria: Mapped[str | None] = mapped_column(Text)
    effectiveness_evidence: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[dt.date | None] = mapped_column(Date)
    effectiveness_result: Mapped[str | None] = mapped_column(Text)
    follow_up_reference: Mapped[str | None] = mapped_column(Text)
    # 7 Cost impact, in US dollars; the total is derived.
    material_loss: Mapped[Decimal | None] = mapped_column(Numeric)
    production_time_loss: Mapped[Decimal | None] = mapped_column(Numeric)
    other_costs: Mapped[Decimal | None] = mapped_column(Numeric)
    quality_cost_record_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(CostRecord.id, name="fk_cars_quality_cost_record", ondelete="RESTRICT"),
    )
    # Optional production references.
    product: Mapped[str | None] = mapped_column(Text)
    campaign: Mapped[str | None] = mapped_column(Text)
    lot: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    counterparty: Mapped[str | None] = mapped_column(Text)
    # Why-Why worksheet: material / delivery information.
    complaint_number: Mapped[str | None] = mapped_column(Text)
    date_reported: Mapped[dt.date | None] = mapped_column(Date)
    dr_number: Mapped[str | None] = mapped_column(Text)
    material_name: Mapped[str | None] = mapped_column(Text)
    po_number: Mapped[str | None] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(Text)
    date_delivered: Mapped[dt.date | None] = mapped_column(Date)
    production_lot: Mapped[str | None] = mapped_column(Text)
    quantity_affected: Mapped[str | None] = mapped_column(Text)
    # Imported reports: older-form values with no current field ([{label, value}]).
    legacy_fields: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB)
    migration_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    source_key: Mapped[str | None] = mapped_column(Text)
    # Source file and cells; kept for audit, not returned by the API.
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


class CarAction(Base):
    """One corrective action (countermeasure) of a report."""

    __tablename__ = "car_actions"
    __table_args__ = (
        CheckConstraint(
            f"btrim(action) <> '' AND char_length(action) <= {MAX_LONG_LENGTH}", name="action"
        ),
        # Imported actions may have no recorded status.
        CheckConstraint(f"status IS NULL OR {_in('status', ACTION_STATUSES)}", name="status"),
        CheckConstraint("completed_on IS NULL OR status = 'complete'", name="completed_on"),
        CheckConstraint("position >= 1", name="position"),
        *(
            CheckConstraint(_optional_text(column, MAX_SHORT_LENGTH), name=column)
            for column in ("owner",)
        ),
        *(
            CheckConstraint(_optional_text(column, MAX_LONG_LENGTH), name=column)
            for column in ("procedures_revised", "supporting_documents")
        ),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_car_actions_car_id", "car_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    car_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(Car.id, name="fk_car_actions_car", ondelete="RESTRICT"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(Text)
    target_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(Text)
    completed_on: Mapped[dt.date | None] = mapped_column(Date)
    procedures_revised: Mapped[str | None] = mapped_column(Text)
    training_completed: Mapped[bool | None] = mapped_column(Boolean)
    supporting_documents: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


WHY_TEXT_FIELDS = ("what", "why", "root_cause", "countermeasure", "who")


class CarWhyStep(Base):
    """One row of the Why-Why worksheet."""

    __tablename__ = "car_why_steps"
    __table_args__ = (
        UniqueConstraint("car_id", "position"),
        CheckConstraint("position >= 1", name="position"),
        *(
            CheckConstraint(_optional_text(column, MAX_LONG_LENGTH), name=column)
            for column in WHY_TEXT_FIELDS
        ),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    car_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(Car.id, name="fk_car_why_steps_car", ondelete="RESTRICT"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    what: Mapped[str | None] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    countermeasure: Mapped[str | None] = mapped_column(Text)
    who: Mapped[str | None] = mapped_column(Text)
    target_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class CarApproval(Base):
    """An approval as recorded on the report: the function, a name and a date.

    This records who approved; it is not an electronic signature.
    ``created_by`` is the platform user who recorded it.
    """

    __tablename__ = "car_approvals"
    __table_args__ = (
        UniqueConstraint("car_id", "function_code"),
        CheckConstraint(_in("function_code", APPROVAL_FUNCTIONS), name="function_code"),
        CheckConstraint(
            f"btrim(name) <> '' AND char_length(name) <= {MAX_SHORT_LENGTH}", name="name"
        ),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    car_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(Car.id, name="fk_car_approvals_car", ondelete="RESTRICT"),
        nullable=False,
    )
    function_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    approved_on: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class CarReference(Base):
    """A link from a report to another record or document (another CAR, a work
    order, a document, a lot...). ``target_type`` names the kind of record and
    ``target_key`` identifies it within that kind."""

    __tablename__ = "car_references"
    __table_args__ = (
        UniqueConstraint("car_id", "target_type", "target_key"),
        CheckConstraint(f"target_type ~ '{REFERENCE_TYPE_PATTERN}'", name="target_type"),
        CheckConstraint(
            f"btrim(target_key) <> '' AND char_length(target_key) <= {MAX_SHORT_LENGTH}",
            name="target_key",
        ),
        CheckConstraint(_optional_text("label", MAX_SHORT_LENGTH), name="label"),
        Index("ix_car_references_target", "target_type", "target_key"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    car_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(Car.id, name="fk_car_references_car", ondelete="RESTRICT"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
