"""Cost of Poor Quality and Cost of Quality calculations.

Every cost, total and percentage is calculated here from the stored monthly
inputs (``quality.cost_monthly_facts``) and never stored. Decimal throughout;
rounding is for display only.

Classes follow the Cost of Quality model: prevention + appraisal = good COQ,
internal + external failure = poor COQ (COPQ). The source records only failure
costs, so prevention, appraisal, good COQ, total COQ and poor COQ % are
unavailable (null), never 0.

A blank input is not reported (null). Sums add the reported parts and are null
only when no part is reported; the parts left out are listed as data checks.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Literal

from app.quality.cost.schemas import (
    CoqClassOut,
    CoqMatrixOut,
    CostElementOut,
    CostMonthOut,
    CostPeriodOut,
    CostSummaryResponse,
    DataCheckOut,
    DefinitionOut,
)

CoqClass = Literal["prevention", "appraisal", "internal_failure", "external_failure"]

COQ_CLASSES: dict[CoqClass, str] = {
    "prevention": "Prevention",
    "appraisal": "Appraisal",
    "internal_failure": "Internal Failure",
    "external_failure": "External Failure",
}

SOURCE = "COQ Matrix.xlsx"


@dataclass(frozen=True)
class MonthInputs:
    """One month's stored inputs. None is not reported."""

    year: int
    month: int
    total_production_lbs: Decimal | None = None
    scrap_produced_lbs: Decimal | None = None
    offspec_produced_lbs: Decimal | None = None
    scrap_loss_per_lb: Decimal | None = None
    offspec_loss_per_lb: Decimal | None = None
    complaint_count: int | None = None
    returned_product_lbs: Decimal | None = None
    outbound_freight: Decimal | None = None
    return_freight: Decimal | None = None
    warehousing_handling: Decimal | None = None
    lab_investigation: Decimal | None = None
    customer_credit_penalty: Decimal | None = None
    complaint_rework_cost: Decimal | None = None
    sales_revenue: Decimal | None = None
    note: str | None = None

    @classmethod
    def from_row(cls, row: object) -> "MonthInputs":
        values = {
            f.name: getattr(row, f.name) for f in fields(cls) if f.name not in ("year", "month")
        }
        return cls(year=row.reporting_year, month=row.reporting_month, **values)  # type: ignore[attr-defined]

    @property
    def reported(self) -> bool:
        return any(
            getattr(self, f.name) is not None
            for f in fields(self)
            if f.name not in ("year", "month", "note")
        )


@dataclass(frozen=True)
class Element:
    code: str
    label: str
    coq_class: CoqClass
    # The COPQ category the element is reported under.
    category: str
    source_term: str


# Cost elements in source order. Scrap and off-spec are calculated (quantity ×
# loss per lb); the complaint lines are dollar amounts in the source.
ELEMENTS: tuple[Element, ...] = (
    Element("scrap", "Scrap", "internal_failure", "Scrap", "Scrap Loss ($)"),
    Element("offspec", "Off-spec", "internal_failure", "Off-spec (C-grade)", "Offspec Loss ($)"),
    Element(
        "outbound_freight",
        "Outbound freight",
        "external_failure",
        "Freight",
        "Outbound Freight ($)",
    ),
    Element(
        "return_freight", "Return freight", "external_failure", "Returns", "Return Freight ($)"
    ),
    Element(
        "warehousing_handling",
        "Warehousing / handling",
        "external_failure",
        "Returns",
        "Warehousing / Handling ($)",
    ),
    Element(
        "lab_investigation",
        "Lab / investigation",
        "external_failure",
        "Investigation",
        "Lab / Investigation ($)",
    ),
    Element(
        "customer_credit_penalty",
        "Customer credit / penalty",
        "external_failure",
        "Customer credits",
        "Customer Credit / Penalty ($)",
    ),
    Element("complaint_rework_cost", "Rework", "external_failure", "Rework", "Rework Cost ($)"),
)

DEFINITIONS: tuple[DefinitionOut, ...] = tuple(
    DefinitionOut(term=term, definition=definition)
    for term, definition in (
        # The workbook's Definitions sheet, verbatim.
        (
            "Production Quality Cost",
            "Internal failure costs incurred before shipment, including scrap and off-spec "
            "material losses.",
        ),
        ("Scrap Produced", "Material that cannot be recovered and is permanently lost."),
        (
            "Offspec Produced",
            "Material that does not meet specification but may be downgraded or reworked.",
        ),
        (
            "Rework Cost",
            "Incremental labor, energy, and handling cost required to reprocess returned or "
            "off-spec material into prime product.",
        ),
        (
            "Customer Complaint Cost",
            "All costs incurred due to customer quality issues after shipment, excluding "
            "recovered material value.",
        ),
        (
            "External Failure Cost",
            "Costs caused by product quality failures after delivery to the customer.",
        ),
        ("Production COQ %", "Production Quality Cost divided by total production value."),
        ("Customer Complaint COQ %", "Customer Complaint Cost divided by sales revenue."),
        (
            "Total Cost of Poor Quality",
            "Sum of internal and external failure costs expressed as a percentage of sales.",
        ),
        (
            "Returned Product Treatment",
            "Returned product is reprocessed and sold as prime; therefore, no material "
            "write-off is recorded.",
        ),
    )
)

# Standing data checks about the source, shown with the calculated ones.
SOURCE_CHECKS: tuple[str, ...] = (
    "Prevention and appraisal costs are not recorded in the source, so good COQ, total COQ "
    "and poor COQ % cannot be calculated. They are shown as not recorded, not as $0.",
    "The workbook's 'Production Value ($)' column holds total production in pounds, so its "
    "'Production COQ %' divides dollars by pounds. Production quality cost is shown here as "
    "dollars per pound produced; percentages use sales revenue only.",
    "The workbook's 'Total Cost of Poor Quality %' divides by production pounds plus sales "
    "dollars. Here COPQ % is COPQ ÷ sales revenue, as the workbook's Definitions sheet states.",
    "Warehousing / handling and complaint rework are calculated in the workbook from returned "
    "pounds ($0.02 and $0.34 per returned pound), not measured costs.",
    "Area, product, owner, status, target and action are not recorded in the source, so "
    "costs cannot be broken down or filtered by them.",
)


def _sum(values: Iterable[Decimal | None]) -> Decimal | None:
    reported = [v for v in values if v is not None]
    return sum(reported, Decimal(0)) if reported else None


def _product(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a * b


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def element_values(month: MonthInputs) -> dict[str, Decimal | None]:
    return {
        "scrap": _product(month.scrap_produced_lbs, month.scrap_loss_per_lb),
        "offspec": _product(month.offspec_produced_lbs, month.offspec_loss_per_lb),
        **{e.code: getattr(month, e.code) for e in ELEMENTS if e.code not in ("scrap", "offspec")},
    }


@dataclass(frozen=True)
class MonthCost:
    inputs: MonthInputs
    elements: dict[str, Decimal | None]
    internal_failure: Decimal | None
    external_failure: Decimal | None
    copq: Decimal | None


def month_cost(month: MonthInputs) -> MonthCost:
    elements = element_values(month)
    by_class = {
        cls: _sum(elements[e.code] for e in ELEMENTS if e.coq_class == cls)
        for cls in ("internal_failure", "external_failure")
    }
    internal = by_class["internal_failure"]
    external = by_class["external_failure"]
    return MonthCost(
        inputs=month,
        elements=elements,
        internal_failure=internal,
        external_failure=external,
        copq=_sum((internal, external)),
    )


def _month_out(cost: MonthCost) -> CostMonthOut:
    m = cost.inputs
    return CostMonthOut(
        year=m.year,
        month=m.month,
        reported=m.reported,
        total_production_lbs=m.total_production_lbs,
        scrap_produced_lbs=m.scrap_produced_lbs,
        offspec_produced_lbs=m.offspec_produced_lbs,
        scrap_loss_per_lb=m.scrap_loss_per_lb,
        offspec_loss_per_lb=m.offspec_loss_per_lb,
        complaint_count=m.complaint_count,
        returned_product_lbs=m.returned_product_lbs,
        sales_revenue=m.sales_revenue,
        elements=cost.elements,
        internal_failure=cost.internal_failure,
        external_failure=cost.external_failure,
        copq=cost.copq,
        internal_cost_per_lb=_ratio(cost.internal_failure, m.total_production_lbs),
        external_pct_of_sales=_ratio(cost.external_failure, m.sales_revenue),
        copq_pct_of_sales=_ratio(cost.copq, m.sales_revenue),
        note=m.note,
    )


def _period(
    costs: Sequence[MonthCost], from_month: int | None, through_month: int | None
) -> CostPeriodOut:
    reported = [c for c in costs if c.inputs.reported]
    internal = _sum(c.internal_failure for c in reported)
    external = _sum(c.external_failure for c in reported)
    copq = _sum((internal, external))
    # Ratios use only months reporting both the cost and the denominator.
    with_sales = [c for c in reported if c.copq is not None and c.inputs.sales_revenue is not None]
    with_production = [
        c
        for c in reported
        if c.internal_failure is not None and c.inputs.total_production_lbs is not None
    ]
    with_sales_external = [
        c for c in reported if c.external_failure is not None and c.inputs.sales_revenue is not None
    ]
    return CostPeriodOut(
        from_month=from_month,
        through_month=through_month,
        months_in_period=len(costs),
        months_reported=len(reported),
        reported_months=[c.inputs.month for c in reported],
        internal_failure=internal,
        external_failure=external,
        copq=copq,
        total_production_lbs=_sum(c.inputs.total_production_lbs for c in reported),
        sales_revenue=_sum(c.inputs.sales_revenue for c in reported),
        complaint_count=(
            sum(c.inputs.complaint_count for c in reported if c.inputs.complaint_count is not None)
            if any(c.inputs.complaint_count is not None for c in reported)
            else None
        ),
        returned_product_lbs=_sum(c.inputs.returned_product_lbs for c in reported),
        copq_pct_of_sales=_ratio(
            _sum(c.copq for c in with_sales), _sum(c.inputs.sales_revenue for c in with_sales)
        ),
        external_pct_of_sales=_ratio(
            _sum(c.external_failure for c in with_sales_external),
            _sum(c.inputs.sales_revenue for c in with_sales_external),
        ),
        internal_cost_per_lb=_ratio(
            _sum(c.internal_failure for c in with_production),
            _sum(c.inputs.total_production_lbs for c in with_production),
        ),
    )


def _elements(costs: Sequence[MonthCost], copq: Decimal | None) -> list[CostElementOut]:
    """Period total per element, highest first (Pareto order); unreported last."""
    rows = [(e, _sum(c.elements[e.code] for c in costs if c.inputs.reported)) for e in ELEMENTS]
    rows.sort(key=lambda row: (row[1] is None, -(row[1] or 0)))
    out: list[CostElementOut] = []
    cumulative = Decimal(0)
    for element, value in rows:
        if value is not None:
            cumulative += value
        out.append(
            CostElementOut(
                code=element.code,
                label=element.label,
                coq_class=element.coq_class,
                category=element.category,
                source_term=element.source_term,
                value=value,
                share_of_copq=_ratio(value, copq),
                cumulative_share=_ratio(cumulative, copq) if value is not None else None,
            )
        )
    return out


def _matrix(period: CostPeriodOut) -> CoqMatrixOut:
    poor = period.copq
    values: dict[CoqClass, Decimal | None] = {
        "prevention": None,
        "appraisal": None,
        "internal_failure": period.internal_failure,
        "external_failure": period.external_failure,
    }
    return CoqMatrixOut(
        classes=[
            CoqClassOut(
                code=code,
                label=label,
                value=values[code],
                recorded=code in ("internal_failure", "external_failure"),
                share_of_recorded=_ratio(values[code], poor),
            )
            for code, label in COQ_CLASSES.items()
        ],
        good=None,
        poor=poor,
        total=None,
        poor_pct=None,
        recorded_total=poor,
        unavailable_reason=(
            "Prevention and appraisal costs are not recorded in the source, so total COQ, "
            "good COQ and poor COQ % cannot be calculated."
        ),
    )


def _checks(costs: Sequence[MonthCost]) -> list[DataCheckOut]:
    checks: list[DataCheckOut] = []
    for cost in costs:
        if not cost.inputs.reported:
            continue
        missing = [e.label for e in ELEMENTS if cost.elements[e.code] is None]
        if missing:
            checks.append(
                DataCheckOut(
                    year=cost.inputs.year,
                    month=cost.inputs.month,
                    status="warning",
                    message=(
                        f"{', '.join(missing)} not reported; the month's totals include only "
                        "the reported lines."
                    ),
                )
            )
        if cost.inputs.sales_revenue is None:
            checks.append(
                DataCheckOut(
                    year=cost.inputs.year,
                    month=cost.inputs.month,
                    status="warning",
                    message="Sales revenue not reported; percentages of sales exclude this month.",
                )
            )
        if cost.inputs.note:
            checks.append(
                DataCheckOut(
                    year=cost.inputs.year,
                    month=cost.inputs.month,
                    status="info",
                    message=cost.inputs.note,
                )
            )
    checks.extend(
        DataCheckOut(year=None, month=None, status="info", message=m) for m in SOURCE_CHECKS
    )
    return checks


def summary(
    stored: Sequence[MonthInputs],
    *,
    year: int | None,
    from_month: int | None,
    through_month: int | None,
) -> CostSummaryResponse:
    """The year's months, the selected period's totals, Pareto and matrix.

    ``year`` defaults to the latest year with data. ``from_month`` defaults to
    January and ``through_month`` to the latest reported month of the year.
    """
    years = sorted({m.year for m in stored if m.reported}, reverse=True)
    selected = year if year is not None else (years[0] if years else None)
    by_month = {m.month: m for m in stored if m.year == selected}
    reported_months = sorted(month for month, m in by_month.items() if m.reported)
    first = from_month or 1
    last = through_month or (reported_months[-1] if reported_months else 12)
    if first > last:
        first, last = last, first
    all_costs = [
        month_cost(by_month.get(month) or MonthInputs(year=selected or 0, month=month))
        for month in range(1, 13)
    ]
    in_period = all_costs[first - 1 : last]
    period = _period(in_period, first, last)
    return CostSummaryResponse(
        year=selected,
        available_years=years,
        latest_reported_month=reported_months[-1] if reported_months else None,
        months=[_month_out(c) for c in all_costs] if selected is not None else [],
        period=period,
        elements=_elements(in_period, period.copq),
        matrix=_matrix(period),
        data_checks=_checks(in_period),
        definitions=list(DEFINITIONS),
        source=SOURCE,
    )
