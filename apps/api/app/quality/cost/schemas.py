"""Cost of Quality API models.

Amounts, quantities and ratios are full-precision decimals sent as plain
strings (never exponent notation); ratios are fractions (0.0051 = 0.51%).
Null is not entered or not calculable, never 0. No response carries a source
cell, file location or import reference.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, PlainSerializer

from app.core.schemas import CamelModel
from app.quality.cost.classification import CoqClass, FinancialStatus, OperationalStatus

DecimalStr = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(value.normalize(), "f"), return_type=str, when_used="json"
    ),
]

CoqClassCode = CoqClass
QualityGroup = Literal["good", "poor"]


class _Input(CamelModel):
    model_config = ConfigDict(extra="forbid")


# --- Quality Cost records ---

Money = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), max_digits=18, decimal_places=4)]
ShortText = Annotated[str, Field(max_length=200)]
LongText = Annotated[str, Field(max_length=4000)]


class ReferenceIn(_Input):
    type: Annotated[str, Field(pattern=r"^[a-z_]+(\.[a-z_]+)*$", max_length=100)]
    key: ShortText
    label: ShortText | None = None


class CostRecordFields(_Input):
    record_date: dt.date
    title: ShortText
    area_id: Annotated[int, Field(ge=1)] | None = None
    coq_class: CoqClassCode
    category_code: Annotated[str, Field(max_length=100)]
    description: LongText
    product: ShortText | None = None
    campaign: ShortText | None = None
    lot: ShortText | None = None
    location: ShortText | None = None
    process: ShortText | None = None
    equipment: ShortText | None = None
    counterparty: ShortText | None = None
    # The owner is a platform user chosen by ID; the server records their name.
    # ``owner`` may only repeat a name recorded before users existed.
    owner_user_id: uuid.UUID | None = None
    owner: ShortText | None = None
    notes: LongText | None = None
    material_cost: Money | None = None
    labor_cost: Money | None = None
    production_cost: Money | None = None
    testing_cost: Money | None = None
    maintenance_cost: Money | None = None
    freight_cost: Money | None = None
    disposal_cost: Money | None = None
    customer_cost: Money | None = None
    other_cost: Money | None = None
    financial_status: FinancialStatus
    status: OperationalStatus
    due_date: dt.date | None = None
    date_closed: dt.date | None = None
    resolution_notes: LongText | None = None
    recovered_cost: Money | None = None
    avoided_cost: Money | None = None
    references: Annotated[list[ReferenceIn], Field(max_length=20)] = []


class CostRecordCreate(CostRecordFields):
    pass


class CostRecordUpdate(CostRecordFields):
    version: Annotated[int, Field(ge=1)]


class ReferenceOut(CamelModel):
    type: str
    type_label: str
    key: str
    label: str | None


class CostRecordOut(CamelModel):
    id: int
    # Display identifier derived from the id, e.g. QC-00042.
    record_number: str
    record_date: dt.date
    title: str
    area_id: int | None
    area_name: str | None
    coq_class: CoqClassCode
    coq_class_label: str
    # Good COQ (prevention, appraisal) or poor COQ (internal, external failure).
    quality_group: QualityGroup
    category_code: str
    category_label: str
    description: str
    product: str | None
    campaign: str | None
    lot: str | None
    location: str | None
    process: str | None
    equipment: str | None
    counterparty: str | None
    owner: str | None
    # Null for a name recorded before users existed.
    owner_user_id: uuid.UUID | None
    notes: str | None
    material_cost: DecimalStr | None
    labor_cost: DecimalStr | None
    production_cost: DecimalStr | None
    testing_cost: DecimalStr | None
    maintenance_cost: DecimalStr | None
    freight_cost: DecimalStr | None
    disposal_cost: DecimalStr | None
    customer_cost: DecimalStr | None
    other_cost: DecimalStr | None
    # Sum of the entered components; null when none is entered.
    total_cost: DecimalStr | None
    financial_status: FinancialStatus
    financial_status_label: str
    # True for Confirmed and Closed; otherwise the total is potential exposure.
    cost_confirmed: bool
    status: OperationalStatus
    status_label: str
    due_date: dt.date | None
    overdue: bool
    date_closed: dt.date | None
    days_open: int
    resolution_notes: str | None
    recovered_cost: DecimalStr | None
    avoided_cost: DecimalStr | None
    # Total less recovered; null when no cost is entered.
    net_cost: DecimalStr | None
    references: list[ReferenceOut]
    source: Literal["manual", "legacy_import"]
    version: int
    created_at: dt.datetime
    created_by: str
    created_by_name: str
    updated_at: dt.datetime
    updated_by: str
    updated_by_name: str


class CostAbilitiesOut(CamelModel):
    """What the signed-in user may do (for the interface; the server enforces it)."""

    create: bool
    edit: bool
    assign: bool
    confirm_financial: bool
    close: bool


class CostRecordListResponse(CamelModel):
    records: list[CostRecordOut]
    total: int
    can_edit: bool
    abilities: CostAbilitiesOut


class CostRecordResponse(CamelModel):
    record: CostRecordOut
    can_edit: bool
    abilities: CostAbilitiesOut


class OptionOut(CamelModel):
    id: int
    code: str
    name: str
    active: bool


class CodeLabelOut(CamelModel):
    code: str
    label: str


class CoqClassOptionOut(CamelModel):
    code: CoqClassCode
    label: str
    quality_group: QualityGroup
    categories: list[CodeLabelOut]


class FinancialStatusOut(CamelModel):
    code: FinancialStatus
    label: str
    confirmed: bool


class CostComponentOut(CamelModel):
    # The camelCase field name on a record.
    field: str
    label: str


class CostRecordOptionsResponse(CamelModel):
    areas: list[OptionOut]
    classes: list[CoqClassOptionOut]
    financial_statuses: list[FinancialStatusOut]
    operational_statuses: list[CodeLabelOut]
    cost_components: list[CostComponentOut]
    reference_types: list[CodeLabelOut]
    # Values already used on records, for filters and entry suggestions.
    products: list[str]
    owners: list[str]
    can_edit: bool
    abilities: CostAbilitiesOut


class HistoryEventOut(CamelModel):
    occurred_at: dt.datetime
    actor_id: str
    # The user's name when the change was made, or a system actor's label.
    actor_name: str
    action: Literal["create", "update", "delete"]
    change_set_id: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None


class HistoryResponse(CamelModel):
    record_id: int
    events: list[HistoryEventOut]


# --- Summary: COPQ and the COQ Matrix, from records ---


class CostFiguresOut(CamelModel):
    """Totals of a set of records (see ``app.quality.cost.calculations``)."""

    count: int
    confirmed_count: int
    potential_count: int
    no_cost_count: int
    confirmed: DecimalStr | None
    potential: DecimalStr | None
    total_exposure: DecimalStr | None
    recovered: DecimalStr | None
    avoided: DecimalStr | None
    net: DecimalStr | None


class CoqClassOut(CamelModel):
    code: CoqClassCode
    label: str
    quality_group: QualityGroup
    figures: CostFiguresOut
    # Confirmed cost of the class ÷ total confirmed COQ.
    share_of_total: DecimalStr | None


class CoqMatrixOut(CamelModel):
    """Good, poor and total COQ, confirmed and potential, never combined."""

    good: DecimalStr | None
    poor: DecimalStr | None
    total: DecimalStr | None
    poor_pct: DecimalStr | None
    good_potential: DecimalStr | None
    poor_potential: DecimalStr | None
    total_potential: DecimalStr | None


class CopqOut(CamelModel):
    figures: CostFiguresOut
    open_count: int
    overdue_count: int
    # Production pounds and sales revenue of the period's months (monthly facts).
    production_lbs: DecimalStr | None
    sales_revenue: DecimalStr | None
    internal_cost_per_lb: DecimalStr | None
    copq_pct_of_sales: DecimalStr | None


class CostMonthOut(CamelModel):
    month: int
    # Confirmed and potential cost per class.
    confirmed: dict[str, DecimalStr | None]
    potential: dict[str, DecimalStr | None]
    good: DecimalStr | None
    poor: DecimalStr | None
    poor_potential: DecimalStr | None
    net_poor: DecimalStr | None
    record_count: int
    production_lbs: DecimalStr | None
    sales_revenue: DecimalStr | None
    copq_pct_of_sales: DecimalStr | None


class CategoryOut(CamelModel):
    coq_class: CoqClassCode
    code: str
    label: str
    figures: CostFiguresOut
    # Confirmed cost ÷ the confirmed cost of its class.
    share_of_class: DecimalStr | None
    # Poor classes only, highest first: running share of confirmed COPQ.
    cumulative_share_of_poor: DecimalStr | None


class AgingBucketOut(CamelModel):
    label: str
    min_days: int
    max_days: int | None
    count: int
    exposure: DecimalStr | None


class DataCheckOut(CamelModel):
    status: Literal["warning", "info"]
    message: str


class DefinitionOut(CamelModel):
    term: str
    definition: str


class CostSummaryResponse(CamelModel):
    year: int | None
    from_month: int
    through_month: int
    available_years: list[int]
    # The latest month of ``year`` with a record.
    latest_month: int | None
    classes: list[CoqClassOut]
    matrix: CoqMatrixOut
    copq: CopqOut
    months: list[CostMonthOut]
    categories: list[CategoryOut]
    # Open poor-quality (failure) records by days open.
    aging: list[AgingBucketOut]
    data_checks: list[DataCheckOut]
    definitions: list[DefinitionOut]


# --- Incident cost estimator (calculated on request; nothing is stored) ---

Quantity = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), max_digits=24, decimal_places=10)]
PositiveQuantity = Annotated[
    Decimal, Field(gt=0, le=Decimal("1e12"), max_digits=24, decimal_places=10)
]
Hours = Annotated[Decimal, Field(ge=0, le=8784, max_digits=12, decimal_places=4)]
PackageType = Literal["Bags", "Box", "Single sacks", "Double stack supersacks"]


class DowntimeIn(_Input):
    downtime_hours: Hours


class LowerProductionIn(_Input):
    flow_rate_lb_per_hour: Quantity
    hours: Hours


class MaterialIn(_Input):
    quantity_lbs: Quantity


class ReworkIn(_Input):
    production_rate_reduction_lb_per_hour: Quantity
    reworking_rate_lb_per_hour: PositiveQuantity
    quantity_lbs: Quantity
    package_type: PackageType
    package_load_lb_per_piece: PositiveQuantity


class RepackIn(_Input):
    quantity_lbs: Quantity
    package_type: PackageType
    package_load_lb_per_piece: PositiveQuantity
    extra_persons: Annotated[int, Field(ge=0, le=1000)]
    overtime_hours_per_person: Hours
    pay_rate_usd_per_hour: Quantity


class EstimateRequest(_Input):
    # Finishing-line product; required for downtime, lower production and rework.
    product: Annotated[str, Field(max_length=20)] | None = None
    downtime: DowntimeIn | None = None
    lower_production: LowerProductionIn | None = None
    scrap: MaterialIn | None = None
    c_grade: MaterialIn | None = None
    rework: ReworkIn | None = None
    repack: RepackIn | None = None


class EstimateStepOut(CamelModel):
    label: str
    value: DecimalStr
    unit: str


class EstimateLineOut(CamelModel):
    code: str
    label: str
    total_kusd: DecimalStr
    formula: str
    steps: list[EstimateStepOut]


class EstimateResponse(CamelModel):
    lines: list[EstimateLineOut]
    total_kusd: DecimalStr
    total_usd: DecimalStr
    warnings: list[str]
    source: str


class EstimatorProductOut(CamelModel):
    code: str
    standard_rate_mt_per_day: DecimalStr


class EstimatorAssumptionOut(CamelModel):
    label: str
    value: DecimalStr
    unit: str


class EstimatorReferenceResponse(CamelModel):
    source: str
    products: list[EstimatorProductOut]
    package_types: list[PackageType]
    assumptions: list[EstimatorAssumptionOut]
    guidance: list[str]
    notes: list[str]
