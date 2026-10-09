"""Cost of Quality storage.

``CostRecord`` (migration 0011) is the one record set behind the Quality Cost
Register, the COPQ dashboard and the COQ Matrix: each record is one quality
cost item classified as Prevention, Appraisal, Internal Failure or External
Failure. Totals, net cost, Good / Poor COQ and days open are derived
(``app.quality.cost.calculations``) and never stored. Records are never
deleted; every change is audited and guarded by ``version``.

``CostMonthlyFact`` (migration 0010) holds the monthly inputs of the COQ
workbook. Its cost lines are converted into records by the reviewed import;
its production pounds and sales revenue remain the denominators for cost per
pound and percent of sales. Null is blank in the source (not reported),
distinct from a recorded 0.
"""

import datetime as dt
import uuid
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, user_link
from app.quality.cost.classification import (
    COMPONENT_FIELDS,
    COQ_CLASSES,
    FINANCIAL_STATUSES,
    OPERATIONAL_STATUSES,
)
from app.quality.moisture.models import QUALITY_SCHEMA
from app.safety.models import Area

MIN_REPORTING_YEAR = 2000
MAX_REPORTING_YEAR = 2100

# Non-negative numeric inputs, in column order.
AMOUNT_COLUMNS = (
    "total_production_lbs",
    "scrap_produced_lbs",
    "offspec_produced_lbs",
    "scrap_loss_per_lb",
    "offspec_loss_per_lb",
    "returned_product_lbs",
    "outbound_freight",
    "return_freight",
    "warehousing_handling",
    "lab_investigation",
    "customer_credit_penalty",
    "complaint_rework_cost",
    "sales_revenue",
)


class CostMonthlyFact(Base):
    __tablename__ = "cost_monthly_facts"
    __table_args__ = (
        UniqueConstraint("reporting_year", "reporting_month"),
        CheckConstraint(
            f"reporting_year BETWEEN {MIN_REPORTING_YEAR} AND {MAX_REPORTING_YEAR}",
            name="reporting_year",
        ),
        CheckConstraint("reporting_month BETWEEN 1 AND 12", name="reporting_month"),
        CheckConstraint("complaint_count >= 0", name="complaint_count"),
        *(CheckConstraint(f"{column} >= 0", name=column) for column in AMOUNT_COLUMNS),
        CheckConstraint("btrim(source) <> ''", name="source"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    reporting_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reporting_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Internal failure inputs.
    total_production_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    scrap_produced_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    offspec_produced_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    scrap_loss_per_lb: Mapped[Decimal | None] = mapped_column(Numeric)
    offspec_loss_per_lb: Mapped[Decimal | None] = mapped_column(Numeric)
    # External failure (customer complaint) inputs, in US dollars.
    complaint_count: Mapped[int | None] = mapped_column(Integer)
    returned_product_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    outbound_freight: Mapped[Decimal | None] = mapped_column(Numeric)
    return_freight: Mapped[Decimal | None] = mapped_column(Numeric)
    warehousing_handling: Mapped[Decimal | None] = mapped_column(Numeric)
    lab_investigation: Mapped[Decimal | None] = mapped_column(Numeric)
    customer_credit_penalty: Mapped[Decimal | None] = mapped_column(Numeric)
    complaint_rework_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    sales_revenue: Mapped[Decimal | None] = mapped_column(Numeric)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # Mapping and source location; kept for audit, not returned by the API.
    source_reference: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


# Quality Cost records (migration 0011) ---------------------------------------------

RECORD_SOURCES = ("manual", "legacy_import")
EARLIEST_RECORD_DATE = dt.date(2000, 1, 1)
MAX_TITLE_LENGTH = 200
MAX_TEXT_LENGTH = 4000
MAX_SHORT_LENGTH = 200
# Optional identification fields, in form order. Product, campaign, lot and
# location use the production identifiers so records can later be related to
# production quality data.
IDENTIFICATION_FIELDS = (
    "product",
    "campaign",
    "lot",
    "location",
    "process",
    "equipment",
    "counterparty",
)
MONEY_FIELDS = (*COMPONENT_FIELDS, "recovered_cost", "avoided_cost")
SOURCE_KEY_INDEX = "uq_cost_records_source_key"
REFERENCE_TYPE_PATTERN = "^[a-z_]+(\\.[a-z_]+)*$"


def _in(column: str, values: Iterable[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _optional_text(column: str, length: int) -> str:
    return f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {length})"


class CostRecord(Base):
    __tablename__ = "cost_records"
    __table_args__ = (
        CheckConstraint(_in("coq_class", COQ_CLASSES), name="coq_class"),
        # A category belongs to the record's class (codes are "<class>.<category>").
        CheckConstraint(
            "category_code ~ '^[a-z_]+\\.[a-z_]+$' "
            "AND split_part(category_code, '.', 1) = coq_class",
            name="category_code",
        ),
        CheckConstraint(_in("financial_status", FINANCIAL_STATUSES), name="financial_status"),
        CheckConstraint(_in("status", OPERATIONAL_STATUSES), name="status"),
        CheckConstraint(_in("source", RECORD_SOURCES), name="source"),
        CheckConstraint(
            f"record_date BETWEEN DATE '{EARLIEST_RECORD_DATE.isoformat()}' AND DATE '2100-12-31'",
            name="record_date",
        ),
        CheckConstraint(
            f"btrim(title) <> '' AND char_length(title) <= {MAX_TITLE_LENGTH}", name="title"
        ),
        CheckConstraint(
            f"btrim(description) <> '' AND char_length(description) <= {MAX_TEXT_LENGTH}",
            name="description",
        ),
        *(
            CheckConstraint(_optional_text(column, MAX_SHORT_LENGTH), name=column)
            for column in (*IDENTIFICATION_FIELDS, "owner")
        ),
        CheckConstraint(_optional_text("notes", MAX_TEXT_LENGTH), name="notes"),
        CheckConstraint(
            _optional_text("resolution_notes", MAX_TEXT_LENGTH), name="resolution_notes"
        ),
        *(CheckConstraint(f"{column} >= 0", name=column) for column in MONEY_FIELDS),
        # An area is required for entered records; imported monthly figures have none.
        CheckConstraint("area_id IS NOT NULL OR source = 'legacy_import'", name="area_required"),
        CheckConstraint("(status = 'closed') = (date_closed IS NOT NULL)", name="closed_has_date"),
        CheckConstraint(
            "date_closed IS NULL OR date_closed >= record_date", name="date_closed_after_date"
        ),
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
        Index("ix_cost_records_record_date", "record_date"),
        Index("ix_cost_records_class_date", "coq_class", "record_date"),
        Index("ix_cost_records_area_date", "area_id", "record_date"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    record_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    area_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(Area.id, name="fk_cost_records_area", ondelete="RESTRICT")
    )
    coq_class: Mapped[str] = mapped_column(Text, nullable=False)
    category_code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    product: Mapped[str | None] = mapped_column(Text)
    campaign: Mapped[str | None] = mapped_column(Text)
    lot: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    process: Mapped[str | None] = mapped_column(Text)
    equipment: Mapped[str | None] = mapped_column(Text)
    # Customer or supplier.
    counterparty: Mapped[str | None] = mapped_column(Text)
    # The owner's name as recorded; ``owner_user_id`` links the platform user when known.
    owner: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = user_link()
    notes: Mapped[str | None] = mapped_column(Text)
    # Cost components in US dollars; null is not entered, distinct from 0.
    material_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    labor_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    production_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    testing_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    maintenance_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    freight_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    disposal_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    customer_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    other_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    financial_status: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    date_closed: Mapped[dt.date | None] = mapped_column(Date)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    recovered_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    avoided_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    # Stable identity of an imported record (the workbook month and cost line),
    # so a re-run of the import finds it instead of adding it again.
    source_key: Mapped[str | None] = mapped_column(Text)
    # Mapping and source location; kept for audit, not returned by the API.
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


class CostRecordReference(Base):
    """A link from a record to another record or document.

    ``target_type`` names what is referenced (``reference`` for a free-text
    document or record number; later e.g. a Corrective Action Report) and
    ``target_key`` identifies it within that type.
    """

    __tablename__ = "cost_record_references"
    __table_args__ = (
        UniqueConstraint("record_id", "target_type", "target_key"),
        CheckConstraint(f"target_type ~ '{REFERENCE_TYPE_PATTERN}'", name="target_type"),
        CheckConstraint(
            f"btrim(target_key) <> '' AND char_length(target_key) <= {MAX_SHORT_LENGTH}",
            name="target_key",
        ),
        CheckConstraint(_optional_text("label", MAX_SHORT_LENGTH), name="label"),
        Index("ix_cost_record_references_target", "target_type", "target_key"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(CostRecord.id, name="fk_cost_record_references_record", ondelete="RESTRICT"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
