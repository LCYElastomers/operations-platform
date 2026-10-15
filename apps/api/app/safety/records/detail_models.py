"""Record-level detail of Incident and Near Miss records (migration 0017).

Each detail table holds at most one row per record and is never the source of
a monthly total. Codes are stable analytical keys checked by a trigger against
``incident_detail_codes`` (or, for the LOPC contributing factor, the existing
``lopc_contributing_factor`` categories); names may change, codes never do.
A null field is not recorded (unknown), never "no" or zero.

Records are never deleted, so each link is ON DELETE RESTRICT. Removing a
detail deletes its row; the audit trail (core.audit_events) keeps the values.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.safety.models import SAFETY_SCHEMA, MetricCategory
from app.safety.records.models import IncidentRecord


def _text(column: str, limit: int) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {limit})",
        name=column,
    )


class IncidentDetailCode(Base):
    __tablename__ = "incident_detail_codes"
    __table_args__ = (
        PrimaryKeyConstraint("taxonomy", "code", name="pk_incident_detail_codes"),
        CheckConstraint("taxonomy ~ '^[a-z_]{1,60}$'", name="taxonomy"),
        CheckConstraint("code ~ '^[A-Za-z0-9_]{1,60}$'", name="code"),
        CheckConstraint(
            "name = btrim(name) AND name <> '' AND char_length(name) <= 200", name="name"
        ),
        {"schema": SAFETY_SCHEMA},
    )

    taxonomy: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _record_id(table: str) -> Mapped[int]:
    return mapped_column(
        BigInteger,
        ForeignKey(IncidentRecord.id, name=f"fk_{table}_incident_record", ondelete="RESTRICT"),
        nullable=False,
    )


class _Audited:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class IncidentRecordClassification(Base):
    """A further Incident Classification of a record, beside its
    ``classification_category_id``."""

    __tablename__ = "incident_record_classifications"
    __table_args__ = (
        UniqueConstraint(
            "incident_record_id",
            "classification_category_id",
            name="uq_incident_record_classifications_record_category",
        ),
        Index(
            "ix_incident_record_classifications_classification_category_id",
            "classification_category_id",
        ),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_record_id: Mapped[int] = _record_id("incident_record_classifications")
    classification_category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            MetricCategory.id,
            name="fk_incident_record_classifications_classification",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class IncidentLopcDetails(_Audited, Base):
    __tablename__ = "incident_lopc_details"
    __table_args__ = (
        UniqueConstraint("incident_record_id", name="uq_incident_lopc_details_incident_record_id"),
        CheckConstraint(
            "estimated_quantity IS NULL OR estimated_quantity >= 0", name="estimated_quantity"
        ),
        CheckConstraint(
            "(estimated_quantity IS NULL) = (quantity_unit_code IS NULL)",
            name="quantity_with_unit",
        ),
        _text("material_name", 200),
        _text("equipment_tag", 100),
        _text("notes", 2000),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_record_id: Mapped[int] = _record_id("incident_lopc_details")
    is_lopc: Mapped[bool | None] = mapped_column(Boolean)
    material_name: Mapped[str | None] = mapped_column(Text)
    estimated_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    quantity_unit_code: Mapped[str | None] = mapped_column(Text)
    equipment_tag: Mapped[str | None] = mapped_column(Text)
    failure_mechanism_code: Mapped[str | None] = mapped_column(Text)
    contributing_factor_code: Mapped[str | None] = mapped_column(Text)
    secondary_containment_status_code: Mapped[str | None] = mapped_column(Text)
    process_safety_incident: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


class IncidentDamageDetails(_Audited, Base):
    __tablename__ = "incident_damage_details"
    __table_args__ = (
        UniqueConstraint(
            "incident_record_id", name="uq_incident_damage_details_incident_record_id"
        ),
        CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="estimated_cost"),
        CheckConstraint(
            "(estimated_cost IS NULL) = (currency_code IS NULL)", name="cost_with_currency"
        ),
        _text("asset_or_property_name", 200),
        _text("equipment_tag", 100),
        _text("asset_type", 100),
        _text("damage_description", 2000),
        _text("operational_impact", 2000),
        _text("work_order_reference", 100),
        _text("notes", 2000),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_record_id: Mapped[int] = _record_id("incident_damage_details")
    damage_kind_code: Mapped[str | None] = mapped_column(Text)
    asset_or_property_name: Mapped[str | None] = mapped_column(Text)
    equipment_tag: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[str | None] = mapped_column(Text)
    damage_description: Mapped[str | None] = mapped_column(Text)
    operational_impact: Mapped[str | None] = mapped_column(Text)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency_code: Mapped[str | None] = mapped_column(Text)
    work_order_reference: Mapped[str | None] = mapped_column(Text)
    out_of_service: Mapped[bool | None] = mapped_column(Boolean)
    repair_required: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


class IncidentPitDetails(_Audited, Base):
    __tablename__ = "incident_pit_details"
    __table_args__ = (
        UniqueConstraint("incident_record_id", name="uq_incident_pit_details_incident_record_id"),
        _text("vehicle_identifier", 100),
        _text("vehicle_type", 100),
        _text("operating_company", 200),
        _text("impacted_asset_or_property", 200),
        _text("notes", 2000),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_record_id: Mapped[int] = _record_id("incident_pit_details")
    vehicle_identifier: Mapped[str | None] = mapped_column(Text)
    vehicle_type: Mapped[str | None] = mapped_column(Text)
    ownership_type_code: Mapped[str | None] = mapped_column(Text)
    operating_company: Mapped[str | None] = mapped_column(Text)
    impacted_asset_or_property: Mapped[str | None] = mapped_column(Text)
    damage_occurred: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


class IncidentSeriousRiskDetails(_Audited, Base):
    """The record-level PSIF designation. PSIF is independent of the record's
    classifications; severity and category are given only for a PSIF."""

    __tablename__ = "incident_serious_risk_details"
    __table_args__ = (
        UniqueConstraint(
            "incident_record_id", name="uq_incident_serious_risk_details_incident_record_id"
        ),
        CheckConstraint(
            "is_psif OR (potential_severity_code IS NULL AND serious_risk_category_code IS NULL)",
            name="severity_needs_psif",
        ),
        _text("rationale", 2000),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_record_id: Mapped[int] = _record_id("incident_serious_risk_details")
    is_psif: Mapped[bool] = mapped_column(Boolean, nullable=False)
    potential_severity_code: Mapped[str | None] = mapped_column(Text)
    serious_risk_category_code: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
