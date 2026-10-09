"""Cost of Poor Quality and Cost of Quality Matrix figures.

The COPQ dashboard and the COQ Matrix are both calculated here from the same
Quality Cost records, using ``app.quality.cost.calculations`` for every
figure, so the two always agree with each other and with the Register.
COPQ is the Internal and External Failure records; the matrix uses all four
classes. Confirmed cost and potential exposure are kept apart throughout.

The monthly COQ workbook inputs (``quality.cost_monthly_facts``) supply only
the denominators (production pounds, sales revenue); their cost lines reach
these figures as imported records. ``MonthInputs`` and ``month_cost`` remain
for the import, which converts and cross-checks those lines.
"""

import calendar
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal

from app.quality.cost import calculations
from app.quality.cost.classification import (
    COQ_CLASSES,
    GOOD_CLASSES,
    POOR_CLASSES,
    CoqClass,
    category_label,
    is_poor,
    quality_group,
)
from app.quality.cost.models import CostRecord
from app.quality.cost.schemas import (
    AgingBucketOut,
    CategoryOut,
    CopqOut,
    CoqClassOut,
    CoqMatrixOut,
    CostFiguresOut,
    CostMonthOut,
    CostSummaryResponse,
    DataCheckOut,
    DefinitionOut,
)

SOURCE = "COQ Matrix.xlsx"
IMPORTED_NOTE = (
    "Records marked Imported are the monthly scrap, off-spec and customer complaint totals "
    "from COQ Matrix.xlsx; they have no area, product or owner."
)


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

_sum = calculations.total
_ratio = calculations.ratio


def _product(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a * b


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


def _figures(records: Sequence[CostRecord]) -> CostFiguresOut:
    t = calculations.totals(records)
    return CostFiguresOut(
        count=t.count,
        confirmed_count=t.confirmed_count,
        potential_count=t.potential_count,
        no_cost_count=t.no_cost_count,
        confirmed=t.confirmed,
        potential=t.potential,
        total_exposure=t.total_exposure,
        recovered=t.recovered,
        avoided=t.avoided,
        net=t.net,
    )


def _class_amounts(records: Sequence[CostRecord], *, confirmed: bool) -> dict[str, Decimal | None]:
    selected = [
        r
        for r in records
        if (calculations.is_confirmed(r) if confirmed else calculations.is_potential(r))
    ]
    return {
        code: _sum(calculations.record_total(r) for r in selected if r.coq_class == code)
        for code in COQ_CLASSES
    }


def _matrix(records: Sequence[CostRecord]) -> CoqMatrixOut:
    confirmed = calculations.matrix(_class_amounts(records, confirmed=True))
    potential = calculations.matrix(_class_amounts(records, confirmed=False))
    return CoqMatrixOut(
        good=confirmed.good,
        poor=confirmed.poor,
        total=confirmed.total,
        poor_pct=confirmed.poor_pct,
        good_potential=potential.good,
        poor_potential=potential.poor,
        total_potential=_sum((potential.good, potential.poor)),
    )


def _fact_sum(facts: dict[int, MonthInputs], months: Sequence[int], name: str) -> Decimal | None:
    return _sum(getattr(facts[m], name) for m in months if m in facts)


def _copq(
    records: Sequence[CostRecord],
    facts: dict[int, MonthInputs],
    months: Sequence[int],
    today: dt.date,
) -> CopqOut:
    poor = calculations.poor_records(records)
    figures = _figures(poor)  # type: ignore[arg-type]

    def confirmed_in(month_list: Sequence[int], classes: tuple[str, ...]) -> Decimal | None:
        return _sum(
            calculations.record_total(r)
            for r in poor
            if r.record_date.month in month_list
            and r.coq_class in classes
            and calculations.is_confirmed(r)
        )

    # Ratios use only months reporting the denominator.
    with_sales = [m for m in months if m in facts and facts[m].sales_revenue is not None]
    with_production = [
        m for m in months if m in facts and facts[m].total_production_lbs is not None
    ]
    return CopqOut(
        figures=figures,
        open_count=sum(1 for r in poor if calculations.is_open(r)),
        overdue_count=sum(1 for r in poor if calculations.is_overdue(r, today)),
        production_lbs=_fact_sum(facts, months, "total_production_lbs"),
        sales_revenue=_fact_sum(facts, months, "sales_revenue"),
        internal_cost_per_lb=_ratio(
            confirmed_in(with_production, ("internal_failure",)),
            _fact_sum(facts, with_production, "total_production_lbs"),
        ),
        copq_pct_of_sales=_ratio(
            confirmed_in(with_sales, ("internal_failure", "external_failure")),
            _fact_sum(facts, with_sales, "sales_revenue"),
        ),
    )


def _months(records: Sequence[CostRecord], facts: dict[int, MonthInputs]) -> list[CostMonthOut]:
    out = []
    for month in range(1, 13):
        inside = [r for r in records if r.record_date.month == month]
        confirmed = _class_amounts(inside, confirmed=True)
        potential = _class_amounts(inside, confirmed=False)
        figures = calculations.matrix(confirmed)
        poor = calculations.totals(calculations.poor_records(inside))  # type: ignore[arg-type]
        fact = facts.get(month)
        sales = fact.sales_revenue if fact else None
        out.append(
            CostMonthOut(
                month=month,
                confirmed=confirmed,
                potential=potential,
                good=figures.good,
                poor=figures.poor,
                poor_potential=calculations.matrix(potential).poor,
                net_poor=poor.net,
                record_count=len(inside),
                production_lbs=fact.total_production_lbs if fact else None,
                sales_revenue=sales,
                copq_pct_of_sales=_ratio(figures.poor, sales),
            )
        )
    return out


def _categories(records: Sequence[CostRecord]) -> list[CategoryOut]:
    by_class = _class_amounts(records, confirmed=True)
    groups: dict[str, list[CostRecord]] = {}
    for record in records:
        groups.setdefault(record.category_code, []).append(record)
    rows = [(code, inside, _figures(inside)) for code, inside in groups.items()]
    # Highest confirmed cost first; categories with no confirmed cost last.
    rows.sort(key=lambda row: (row[2].confirmed is None, -(row[2].confirmed or 0), row[0]))
    poor_total = _sum(by_class[c] for c in POOR_CLASSES)
    cumulative = Decimal(0)
    out = []
    for code, inside, figures in rows:
        coq_class = inside[0].coq_class
        share_of_poor = None
        if is_poor(coq_class) and figures.confirmed is not None:
            cumulative += figures.confirmed
            share_of_poor = _ratio(cumulative, poor_total)
        out.append(
            CategoryOut(
                coq_class=coq_class,  # type: ignore[arg-type]
                code=code,
                label=category_label(code),
                figures=figures,
                share_of_class=_ratio(figures.confirmed, by_class[coq_class]),
                cumulative_share_of_poor=share_of_poor,
            )
        )
    return out


def _checks(
    records: Sequence[CostRecord],
    facts: dict[int, MonthInputs],
    months: Sequence[int],
) -> list[DataCheckOut]:
    checks: list[DataCheckOut] = []
    figures = calculations.totals(records)
    if figures.no_cost_count:
        checks.append(
            DataCheckOut(
                status="warning",
                message=f"{_records(figures.no_cost_count)} no cost entered yet; "
                "counted, but adding nothing to the totals.",
            )
        )
    if figures.potential_count:
        checks.append(
            DataCheckOut(
                status="info",
                message=f"{_records(figures.potential_count)} Potential or Validating: "
                "shown as potential exposure, not in confirmed cost.",
            )
        )
    present = {r.coq_class for r in records if calculations.is_confirmed(r)}
    if records and not present & GOOD_CLASSES:
        checks.append(
            DataCheckOut(
                status="info",
                message="No confirmed Prevention or Appraisal cost is recorded for this selection, "
                "so good COQ, total COQ and poor COQ % are shown as not recorded, not as $0.",
            )
        )
    poor_months = sorted(
        {
            r.record_date.month
            for r in records
            if is_poor(r.coq_class) and calculations.is_confirmed(r)
        }
    )
    without_sales = [
        m for m in poor_months if m in months and (m not in facts or facts[m].sales_revenue is None)
    ]
    if without_sales:
        checks.append(
            DataCheckOut(
                status="warning",
                message="Sales revenue is not reported for "
                f"{', '.join(calendar.month_abbr[m] for m in without_sales)}; "
                "COPQ % of sales leaves those months out.",
            )
        )
    if any(r.source == "legacy_import" for r in records):
        checks.append(DataCheckOut(status="info", message=IMPORTED_NOTE))
    for month in months:
        if month in facts and facts[month].note:
            checks.append(
                DataCheckOut(
                    status="info", message=f"{calendar.month_abbr[month]}: {facts[month].note}"
                )
            )
    return checks


def _records(count: int) -> str:
    return "1 record has" if count == 1 else f"{count} records have"


def summary(
    records: Sequence[CostRecord],
    stored: Sequence[MonthInputs],
    *,
    year: int | None,
    available_years: Sequence[int],
    from_month: int | None,
    through_month: int | None,
    today: dt.date,
) -> CostSummaryResponse:
    """COPQ and COQ Matrix figures of ``records`` (already filtered to ``year``
    and the selected dimensions) for ``from_month`` through ``through_month``.

    ``through_month`` defaults to the latest month of the year with a record.
    """
    in_year = [r for r in records if year is not None and r.record_date.year == year]
    record_months = sorted({r.record_date.month for r in in_year})
    first = from_month or 1
    last = through_month or (record_months[-1] if record_months else 12)
    if first > last:
        first, last = last, first
    months = list(range(first, last + 1))
    facts = {m.month: m for m in stored if m.year == year}
    in_period = [r for r in in_year if r.record_date.month in months]
    matrix = _matrix(in_period)
    return CostSummaryResponse(
        year=year,
        from_month=first,
        through_month=last,
        available_years=list(available_years),
        latest_month=record_months[-1] if record_months else None,
        classes=[
            CoqClassOut(
                code=code,
                label=label,
                quality_group=quality_group(code),
                figures=_figures([r for r in in_period if r.coq_class == code]),
                share_of_total=_ratio(
                    _class_amounts(in_period, confirmed=True)[code], matrix.total
                ),
            )
            for code, label in COQ_CLASSES.items()
        ],
        matrix=matrix,
        copq=_copq(in_period, facts, months, today),
        months=_months(in_year, facts),
        categories=_categories(in_period),
        aging=[
            AgingBucketOut(
                label=b.label,
                min_days=b.min_days,
                max_days=b.max_days,
                count=b.count,
                exposure=b.exposure,
            )
            for b in calculations.aging(calculations.poor_records(in_period), today)  # type: ignore[arg-type]
        ],
        data_checks=_checks(in_period, facts, months),
        definitions=list(DEFINITIONS),
    )
