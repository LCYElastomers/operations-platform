"""Quality Cost Register, COPQ and COQ Matrix exports.

The dashboards' figures come from ``load_summary`` (the code behind
``GET /quality/cost/summary``) and the register rows from ``register_filter``
and the repository search behind ``GET /quality/cost/records``. COPQ and the
COQ Matrix report months within one year, like their screens.
"""

import calendar
import datetime as dt
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.permissions import Permission
from app.quality.cost import records
from app.quality.cost.classification import (
    CATEGORIES,
    COQ_CLASSES,
    FINANCIAL_STATUSES,
    OPERATIONAL_STATUSES,
    POOR_CLASSES,
    CoqClass,
    FinancialStatus,
    OperationalStatus,
)
from app.quality.cost.repository import CostRepository
from app.quality.cost.router import load_summary, register_filter
from app.quality.cost.schemas import CostRecordOut, CostSummaryResponse
from app.reports.definitions import ReportContent, ReportContext, ReportDefinition
from app.reports.model import Chart, Column, Kpi, Series, Table, Value
from app.reports.period import Period

MODULE = "Quality · Cost of Quality"
CLASS_ORDER: list[CoqClass] = ["prevention", "appraisal", "internal_failure", "external_failure"]
CLASS_COLORS = {
    "prevention": "#059669",
    "appraisal": "#0d9488",
    "internal_failure": "#ea580c",
    "external_failure": "#dc2626",
}
POTENTIAL_COLOR = "#a855f7"
# Periods of one or more whole months within one year.
SUMMARY_MODES = frozenset({"this-month", "last-month", "ytd", "this-year", "year", "month"})

Text = Annotated[str, StringConstraints(max_length=200)]


class CostDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    area_id: int | None = Field(default=None, ge=1, alias="areaId")
    coq_class: CoqClass | None = Field(default=None, alias="coqClass")
    category: Annotated[str, StringConstraints(max_length=100)] | None = None
    product: Text | None = None
    owner: Text | None = None
    financial_status: FinancialStatus | None = Field(default=None, alias="financialStatus")


class CostRegisterFilters(CostDimensions):
    status: OperationalStatus | None = None
    open: bool = False
    classes: list[CoqClass] = Field(default_factory=list, max_length=4)
    search: Text | None = None


def _dimension_filters(ctx: ReportContext, f: CostDimensions) -> list[tuple[str, str]]:
    applied: list[tuple[str, str]] = []
    if f.area_id is not None:
        names = {a.id: a.name for a in CostRepository(ctx.session).areas()}
        applied.append(("Area", names.get(f.area_id, f"#{f.area_id}")))
    if f.coq_class:
        applied.append(("COQ class", COQ_CLASSES[f.coq_class]))
    if f.category:
        label = next((c.label for c in CATEGORIES if c.code == f.category), f.category)
        applied.append(("Category", label))
    if f.product:
        applied.append(("Product", f.product))
    if f.owner:
        applied.append(("Owner", f.owner))
    if f.financial_status:
        applied.append(("Financial status", FINANCIAL_STATUSES[f.financial_status]))
    return applied


def _months(period: Period) -> tuple[int | None, int | None, int | None]:
    """(year, from month, through month) of a whole-month period in one year.
    A whole year leaves the months open: the summary runs January through the
    latest month with records, as on screen."""
    if period.start is None or period.end is None:
        return None, None, None
    if period.mode in ("this-year", "year"):
        return period.start.year, None, None
    return period.start.year, period.start.month, period.end.month


def _summary(ctx: ReportContext, poor_only: bool) -> CostSummaryResponse:
    f = ctx.filters
    assert isinstance(f, CostDimensions)  # noqa: S101 - set by the definition
    year, first, last = _months(ctx.period)
    return load_summary(
        CostRepository(ctx.session),
        year=year,
        from_month=first,
        through=last,
        area_id=f.area_id,
        coq_class=[f.coq_class] if f.coq_class else None,
        category=f.category,
        product=f.product,
        owner=f.owner,
        financial_status=[f.financial_status] if f.financial_status else None,
        poor_only=poor_only,
    )


def _span(data: CostSummaryResponse) -> str:
    if data.year is None:
        return "No records"
    first = calendar.month_abbr[data.from_month]
    last = calendar.month_abbr[data.through_month]
    return f"{last} {data.year}" if first == last else f"{first}–{last} {data.year}"


def _period_label(ctx: ReportContext, data: CostSummaryResponse) -> str:
    """The period and the months the figures cover (a whole year runs through
    the latest month with records)."""
    if ctx.period.mode == "month":
        return ctx.period.label
    return f"{ctx.period.label} · {_span(data)}"


def _in_period(data: CostSummaryResponse):
    return [m for m in data.months if data.from_month <= m.month <= data.through_month]


def _records(
    ctx: ReportContext, data: CostSummaryResponse, *, classes: list[CoqClass], open_only: bool
) -> list[CostRecordOut]:
    if data.year is None:
        return []
    f = ctx.filters
    assert isinstance(f, CostDimensions)  # noqa: S101 - set by the definition
    last_day = calendar.monthrange(data.year, data.through_month)[1]
    criteria = register_filter(
        date_from=dt.date(data.year, data.from_month, 1),
        date_to=dt.date(data.year, data.through_month, last_day),
        area_id=f.area_id,
        coq_class=[f.coq_class] if f.coq_class else classes or None,
        category=f.category,
        product=f.product,
        owner=f.owner,
        financial_status=[f.financial_status] if f.financial_status else None,
        record_status=None,
        open_only=open_only,
        search=None,
    )
    return _record_list(ctx, criteria)


def _record_list(ctx: ReportContext, criteria) -> list[CostRecordOut]:
    repository = CostRepository(ctx.session)
    rows, _ = repository.search(criteria)
    names = repository.actor_names(records.actor_ids(rows))
    return [records.record_out(r, ctx.today, names) for r in rows]


RECORD_COLUMNS = [
    Column("Record", "text", 10),
    Column("Date", "date", 11),
    Column("Title", "text", 36),
    Column("Area", "text", 16),
    Column("COQ Class", "text", 16),
    Column("Category", "text", 24),
    Column("Product", "text", 14),
    Column("Lot", "text", 12),
    Column("Owner", "text", 18),
    Column("Status", "text", 12),
    Column("Financial Status", "text", 14),
    Column("Total Cost", "money", 14),
    Column("Cost Confirmed", "text", 9),
    Column("Recovered", "money", 13),
    Column("Avoided", "money", 13),
    Column("Net Cost", "money", 13),
    Column("Due Date", "date", 11),
    Column("Overdue", "text", 8),
    Column("Days Open", "int", 9),
    Column("Date Closed", "date", 11),
]
PDF_RECORD_COLUMNS = [0, 1, 2, 4, 5, 8, 9, 10, 11, 18]


def _record_row(r: CostRecordOut) -> list[Value]:
    return [
        r.record_number,
        r.record_date,
        r.title,
        r.area_name,
        r.coq_class_label,
        r.category_label,
        r.product,
        r.lot,
        r.owner,
        r.status_label,
        r.financial_status_label,
        r.total_cost,
        "Yes" if r.cost_confirmed else "No",
        r.recovered_cost,
        r.avoided_cost,
        r.net_cost,
        r.due_date,
        "Yes" if r.overdue else "No",
        r.days_open,
        r.date_closed,
    ]


def _records_table(
    title: str, rows: list[CostRecordOut], sheet: str, description: str = "", in_pdf: bool = True
) -> Table:
    return Table(
        title,
        RECORD_COLUMNS,
        [_record_row(r) for r in rows],
        description=description,
        sheet=sheet,
        in_pdf=in_pdf,
        pdf_columns=PDF_RECORD_COLUMNS,
        pdf_row_limit=150,
    )


def _notes(data: CostSummaryResponse) -> list[str]:
    return [f"Data check: {c.message}" for c in data.data_checks] + [
        f"{d.term}: {d.definition}" for d in data.definitions
    ]


# --- COPQ ---------------------------------------------------------------------


def build_copq(ctx: ReportContext) -> ReportContent:
    data = _summary(ctx, poor_only=True)
    copq, figures = data.copq, data.copq.figures
    months = _in_period(data)
    rows = [c for c in data.categories if c.coq_class in POOR_CLASSES]
    labels = {c.code: c.label for c in data.classes}
    open_items = _records(ctx, data, classes=sorted(POOR_CLASSES), open_only=True)
    return ReportContent(
        filters=_dimension_filters(ctx, ctx.filters),  # type: ignore[arg-type]
        subtitle="Cost of Poor Quality = Internal Failure + External Failure. "
        "Confirmed cost and potential exposure are never added together.",
        period_label=_period_label(ctx, data),
        kpis=[
            Kpi(
                "Confirmed COPQ",
                figures.confirmed,
                "money",
                caption=f"{figures.confirmed_count} records confirmed",
            ),
            Kpi(
                "Potential exposure",
                figures.potential,
                "money",
                caption=f"{figures.potential_count} Potential or Validating; not in COPQ",
            ),
            Kpi("Net COPQ", figures.net, "money", caption="Confirmed COPQ less recovered"),
            Kpi(
                "COPQ % of sales",
                copq.copq_pct_of_sales,
                "percent",
                caption="Sales revenue not reported"
                if copq.sales_revenue is None
                else "Confirmed COPQ ÷ sales revenue",
            ),
            Kpi("Recovered", figures.recovered, "money"),
            Kpi("Avoided", figures.avoided, "money", caption="Not deducted from COPQ"),
            Kpi(
                "Internal failure per lb",
                copq.internal_cost_per_lb,
                "money4",
                caption="Production not reported"
                if copq.production_lbs is None
                else "Per lb produced",
            ),
            Kpi("Open items", copq.open_count, caption=f"{copq.overdue_count} overdue"),
        ],
        charts=[
            Chart(
                "COPQ Pareto by category",
                [r.label for r in rows],
                [
                    Series(
                        "Internal failure",
                        [
                            r.figures.confirmed if r.coq_class == "internal_failure" else None
                            for r in rows
                        ],
                        CLASS_COLORS["internal_failure"],
                    ),
                    Series(
                        "External failure",
                        [
                            r.figures.confirmed if r.coq_class == "external_failure" else None
                            for r in rows
                        ],
                        CLASS_COLORS["external_failure"],
                    ),
                    Series(
                        "Potential exposure", [r.figures.potential for r in rows], POTENTIAL_COLOR
                    ),
                ],
                value_type="money",
                x_label="Category",
                description="Confirmed cost, largest first; potential exposure beside it, "
                "not added.",
            ),
            Chart(
                "Monthly COPQ trend",
                [calendar.month_abbr[m.month] for m in months],
                [
                    Series(
                        "Internal failure",
                        [m.confirmed.get("internal_failure") for m in months],
                        CLASS_COLORS["internal_failure"],
                    ),
                    Series(
                        "External failure",
                        [m.confirmed.get("external_failure") for m in months],
                        CLASS_COLORS["external_failure"],
                    ),
                    Series(
                        "Potential exposure", [m.poor_potential for m in months], POTENTIAL_COLOR
                    ),
                ],
                value_type="money",
                x_label="Month",
            ),
        ],
        tables=[
            Table(
                f"COPQ by month, {data.year}" if data.year else "COPQ by month",
                [
                    Column("Month", "text", 10),
                    Column("Items", "int", 8),
                    Column("Internal failure", "money", 15),
                    Column("External failure", "money", 15),
                    Column("Confirmed COPQ", "money", 15),
                    Column("Net COPQ", "money", 15),
                    Column("Potential exposure", "money", 15),
                    Column("Sales revenue", "money", 15),
                    Column("COPQ % of sales", "percent", 12),
                ],
                [
                    [
                        calendar.month_name[m.month],
                        m.record_count,
                        m.confirmed.get("internal_failure"),
                        m.confirmed.get("external_failure"),
                        m.poor,
                        m.net_poor,
                        m.poor_potential,
                        m.sales_revenue,
                        m.copq_pct_of_sales,
                    ]
                    for m in months
                ],
                sheet="COPQ by Month",
            ),
            Table(
                "COPQ by category",
                [
                    Column("Category", "text", 30),
                    Column("Class", "text", 16),
                    Column("Items", "int", 8),
                    Column("Confirmed", "money", 15),
                    Column("Potential exposure", "money", 15),
                    Column("Recovered", "money", 15),
                    Column("Net", "money", 15),
                    Column("Cumulative share of COPQ", "percent", 12),
                ],
                [
                    [
                        r.label,
                        labels.get(r.coq_class, r.coq_class),
                        r.figures.count,
                        r.figures.confirmed,
                        r.figures.potential,
                        r.figures.recovered,
                        r.figures.net,
                        r.cumulative_share_of_poor,
                    ]
                    for r in rows
                ],
                sheet="COPQ by Category",
            ),
            Table(
                "Open item aging",
                [
                    Column("Days open", "text", 14),
                    Column("Items", "int", 8),
                    Column("Cost or exposure", "money", 16),
                ],
                [[b.label, b.count, b.exposure] for b in data.aging],
                description="Open failure items by days since the item date.",
                sheet="Open Item Aging",
            ),
            _records_table(
                "Open failure items",
                open_items,
                "Open Failure Items",
                "Items not yet Closed, newest first.",
            ),
        ],
        notes=_notes(data),
        filename_period=None,
    )


# --- COQ Matrix ---------------------------------------------------------------


def build_matrix(ctx: ReportContext) -> ReportContent:
    data = _summary(ctx, poor_only=False)
    matrix = data.matrix
    months = _in_period(data)
    by_code = {c.code: c for c in data.classes}
    categories = sorted(data.categories, key=lambda c: CLASS_ORDER.index(c.coq_class))
    items = _records(ctx, data, classes=[], open_only=False)
    return ReportContent(
        filters=_dimension_filters(ctx, ctx.filters),  # type: ignore[arg-type]
        subtitle="Good quality costs (prevention + appraisal) and poor quality costs "
        "(internal + external failure). Potential exposure is never added in.",
        period_label=_period_label(ctx, data),
        kpis=[
            Kpi(
                "Total COQ",
                matrix.total,
                "money",
                caption="Plus potential exposure" if matrix.total_potential else "",
            ),
            Kpi("Good COQ (P + A)", matrix.good, "money"),
            Kpi("Poor COQ (IF + EF)", matrix.poor, "money"),
            Kpi("Poor COQ % of total", matrix.poor_pct, "percent"),
            Kpi("Total potential exposure", matrix.total_potential, "money"),
            *(
                Kpi(
                    by_code[code].label,
                    by_code[code].figures.confirmed,
                    "money",
                    caption=f"{by_code[code].figures.count} items",
                )
                for code in CLASS_ORDER
                if code in by_code
            ),
        ],
        charts=[
            Chart(
                "COQ by class and month",
                [calendar.month_abbr[m.month] for m in months],
                [
                    Series(
                        by_code[code].label if code in by_code else COQ_CLASSES[code],
                        [m.confirmed.get(code) for m in months],
                        CLASS_COLORS[code],
                    )
                    for code in CLASS_ORDER
                ],
                value_type="money",
                x_label="Month",
                description="Confirmed cost by class.",
            ),
            Chart(
                "Confirmed cost by class",
                [by_code[c].label for c in CLASS_ORDER if c in by_code],
                [
                    Series(
                        "Confirmed",
                        [by_code[c].figures.confirmed for c in CLASS_ORDER if c in by_code],
                        "#2563eb",
                    ),
                    Series(
                        "Potential exposure",
                        [by_code[c].figures.potential for c in CLASS_ORDER if c in by_code],
                        POTENTIAL_COLOR,
                    ),
                ],
                value_type="money",
                x_label="Class",
            ),
        ],
        tables=[
            Table(
                "Cost of Quality matrix",
                [
                    Column("Class", "text", 18),
                    Column("Items", "int", 8),
                    Column("Confirmed", "money", 15),
                    Column("Share of total COQ", "percent", 12),
                    Column("Potential exposure", "money", 15),
                    Column("Recovered", "money", 15),
                    Column("Avoided", "money", 15),
                    Column("Net", "money", 15),
                ],
                [
                    [
                        c.label,
                        c.figures.count,
                        c.figures.confirmed,
                        c.share_of_total,
                        c.figures.potential,
                        c.figures.recovered,
                        c.figures.avoided,
                        c.figures.net,
                    ]
                    for c in (by_code[code] for code in CLASS_ORDER if code in by_code)
                ],
                sheet="COQ Matrix",
            ),
            Table(
                "COQ by class and month",
                [Column("Month", "text", 10)]
                + [Column(COQ_CLASSES[code], "money", 15) for code in CLASS_ORDER]
                + [Column("Items", "int", 8)],
                [
                    [
                        calendar.month_name[m.month],
                        *(m.confirmed.get(code) for code in CLASS_ORDER),
                        m.record_count,
                    ]
                    for m in months
                ],
                sheet="COQ by Month",
            ),
            Table(
                "COQ by category",
                [
                    Column("Class", "text", 16),
                    Column("Category", "text", 30),
                    Column("Items", "int", 8),
                    Column("Confirmed", "money", 15),
                    Column("Share of class", "percent", 12),
                    Column("Potential exposure", "money", 15),
                    Column("Recovered", "money", 15),
                    Column("Avoided", "money", 15),
                ],
                [
                    [
                        COQ_CLASSES[c.coq_class],
                        c.label,
                        c.figures.count,
                        c.figures.confirmed,
                        c.share_of_class,
                        c.figures.potential,
                        c.figures.recovered,
                        c.figures.avoided,
                    ]
                    for c in categories
                ],
                sheet="COQ by Category",
            ),
            _records_table("Quality cost items", items, "Items", in_pdf=False),
        ],
        notes=_notes(data),
    )


# --- Register -----------------------------------------------------------------


def build_register(ctx: ReportContext) -> ReportContent:
    f = ctx.filters
    assert isinstance(f, CostRegisterFilters)  # noqa: S101 - set by the definition
    criteria = register_filter(
        date_from=ctx.period.start,
        date_to=ctx.period.end,
        area_id=f.area_id,
        coq_class=[f.coq_class] if f.coq_class else (list(f.classes) or None),
        category=f.category,
        product=f.product,
        owner=f.owner,
        financial_status=[f.financial_status] if f.financial_status else None,
        record_status=[f.status] if f.status else None,
        open_only=f.open,
        search=(f.search or "").strip() or None,
    )
    rows = _record_list(ctx, criteria)
    applied = [
        *([("Search", f.search)] if f.search else []),
        *_dimension_filters(ctx, f),
        *([("Status", OPERATIONAL_STATUSES[f.status])] if f.status else []),
        *([("Open items only", "Yes")] if f.open else []),
        *(
            [("COQ classes", ", ".join(COQ_CLASSES[c] for c in f.classes))]
            if f.classes and not f.coq_class
            else []
        ),
    ]
    confirmed = [r.total_cost for r in rows if r.cost_confirmed and r.total_cost is not None]
    potential = [r.total_cost for r in rows if not r.cost_confirmed and r.total_cost is not None]
    return ReportContent(
        filters=applied,
        kpis=[
            Kpi("Matching items", len(rows)),
            Kpi(
                "Confirmed cost",
                sum(confirmed) if confirmed else None,
                "money",
                caption=f"{len(confirmed)} items with confirmed cost",
            ),
            Kpi(
                "Potential exposure",
                sum(potential) if potential else None,
                "money",
                caption=f"{len(potential)} items; not added to confirmed cost",
            ),
            Kpi("Open items", sum(1 for r in rows if r.status != "closed")),
            Kpi("Overdue", sum(1 for r in rows if r.overdue)),
            Kpi(
                "No cost entered",
                sum(1 for r in rows if r.total_cost is None),
                caption="Not counted as $0",
            ),
        ],
        tables=[
            _records_table("Quality Cost Register", rows, "Quality Cost Register", in_pdf=False)
        ],
    )


COPQ = ReportDefinition(
    key="copq",
    title="Cost of Poor Quality",
    module=MODULE,
    filename="COPQ",
    view_permissions=(Permission.QUALITY_COST_VIEW, Permission.QUALITY_DASHBOARD_VIEW),
    export_permission=Permission.QUALITY_COST_EXPORT,
    filters=CostDimensions,
    period_modes=SUMMARY_MODES,
    build=build_copq,
)

MATRIX = ReportDefinition(
    key="coq-matrix",
    title="Cost of Quality Matrix",
    module=MODULE,
    filename="COQ-Matrix",
    view_permissions=(Permission.QUALITY_COST_VIEW, Permission.QUALITY_DASHBOARD_VIEW),
    export_permission=Permission.QUALITY_COST_EXPORT,
    filters=CostDimensions,
    period_modes=SUMMARY_MODES,
    build=build_matrix,
)

REGISTER = ReportDefinition(
    key="quality-cost-register",
    title="Quality Cost Register",
    module=MODULE,
    filename="Quality-Cost-Register",
    view_permissions=(Permission.QUALITY_COST_VIEW,),
    export_permission=Permission.QUALITY_COST_EXPORT,
    filters=CostRegisterFilters,
    formats=("xlsx",),
    build=build_register,
)
