"""Cost of Quality API models.

Amounts, quantities and ratios are full-precision decimals sent as plain
strings (never exponent notation); ratios are fractions (0.0051 = 0.51%).
Null is not reported or not calculable, never 0. No response carries a source
cell or file location.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, PlainSerializer

from app.core.schemas import CamelModel

DecimalStr = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(value.normalize(), "f"), return_type=str, when_used="json"
    ),
]

CoqClassCode = Literal["prevention", "appraisal", "internal_failure", "external_failure"]


class CostMonthOut(CamelModel):
    year: int
    month: int
    reported: bool
    total_production_lbs: DecimalStr | None
    scrap_produced_lbs: DecimalStr | None
    offspec_produced_lbs: DecimalStr | None
    scrap_loss_per_lb: DecimalStr | None
    offspec_loss_per_lb: DecimalStr | None
    complaint_count: int | None
    returned_product_lbs: DecimalStr | None
    sales_revenue: DecimalStr | None
    # Calculated cost per element code (see ``CostElementOut.code``).
    elements: dict[str, DecimalStr | None]
    internal_failure: DecimalStr | None
    external_failure: DecimalStr | None
    copq: DecimalStr | None
    internal_cost_per_lb: DecimalStr | None
    external_pct_of_sales: DecimalStr | None
    copq_pct_of_sales: DecimalStr | None
    note: str | None


class CostPeriodOut(CamelModel):
    from_month: int | None
    through_month: int | None
    months_in_period: int
    months_reported: int
    reported_months: list[int]
    internal_failure: DecimalStr | None
    external_failure: DecimalStr | None
    copq: DecimalStr | None
    total_production_lbs: DecimalStr | None
    sales_revenue: DecimalStr | None
    complaint_count: int | None
    returned_product_lbs: DecimalStr | None
    copq_pct_of_sales: DecimalStr | None
    external_pct_of_sales: DecimalStr | None
    internal_cost_per_lb: DecimalStr | None


class CostElementOut(CamelModel):
    code: str
    label: str
    coq_class: CoqClassCode
    category: str
    # The column heading in the source workbook.
    source_term: str
    value: DecimalStr | None
    share_of_copq: DecimalStr | None
    cumulative_share: DecimalStr | None


class CoqClassOut(CamelModel):
    code: CoqClassCode
    label: str
    value: DecimalStr | None
    # False: the source records no costs of this class (shown as not recorded).
    recorded: bool
    share_of_recorded: DecimalStr | None


class CoqMatrixOut(CamelModel):
    classes: list[CoqClassOut]
    good: DecimalStr | None
    poor: DecimalStr | None
    total: DecimalStr | None
    poor_pct: DecimalStr | None
    recorded_total: DecimalStr | None
    unavailable_reason: str | None


class DataCheckOut(CamelModel):
    year: int | None
    month: int | None
    status: Literal["warning", "info"]
    message: str


class DefinitionOut(CamelModel):
    term: str
    definition: str


class CostSummaryResponse(CamelModel):
    year: int | None
    available_years: list[int]
    latest_reported_month: int | None
    months: list[CostMonthOut]
    period: CostPeriodOut
    elements: list[CostElementOut]
    matrix: CoqMatrixOut
    data_checks: list[DataCheckOut]
    definitions: list[DefinitionOut]
    source: str


# --- Incident cost estimator (calculated on request; nothing is stored) ---

Quantity = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), max_digits=24, decimal_places=10)]
PositiveQuantity = Annotated[
    Decimal, Field(gt=0, le=Decimal("1e12"), max_digits=24, decimal_places=10)
]
Hours = Annotated[Decimal, Field(ge=0, le=8784, max_digits=12, decimal_places=4)]
PackageType = Literal["Bags", "Box", "Single sacks", "Double stack supersacks"]


class _Input(CamelModel):
    model_config = ConfigDict(extra="forbid")


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
