"""Safety dashboard exports: Incident & Near Miss, Safety Performance, TRIR
Experience and Safety Observations.

Safety reports a calendar year through a month (year to date), as its screens
do, so these reports take a "year" period plus the screen's through month. The
figures come from the same service calls as the dashboard endpoints.
"""

import calendar
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.permissions import Permission
from app.reports.definitions import (
    NoFilters,
    ReportContent,
    ReportContext,
    ReportDefinition,
    ReportInputError,
)
from app.reports.model import Chart, Column, Kpi, Series, Table, Value
from app.safety import analytics
from app.safety.analytics import MonthNotStartedError
from app.safety.behavior.repository import DatabaseBehaviorRepository
from app.safety.observations import service as observation_service
from app.safety.observations.repository import DatabaseObservationRepository
from app.safety.performance import service as performance_service
from app.safety.performance.repository import DatabasePerformanceRepository
from app.safety.performance.schemas import RateOut
from app.safety.repository import DatabaseSafetyMetricsRepository
from app.safety.schemas import AnalyticsBreakdownOut, AnalyticsCategoryOut, AnalyticsSeriesOut
from app.safety.trir.router import _experience

MODULE = "Safety"
YEAR_ONLY = frozenset({"year"})
MONTHS = [calendar.month_abbr[m] for m in range(1, 13)]
BLUE, AMBER, RED, GREEN, VIOLET, TEAL, SLATE = (
    "#2563eb",
    "#d97706",
    "#dc2626",
    "#059669",
    "#7c3aed",
    "#0d9488",
    "#64748b",
)

KPI_LABELS = {
    "incidents": "Incidents YTD",
    "near_misses": "Near Misses YTD",
    "lopc": "LOPC YTD",
    "psif": "PSIF YTD",
    "pit": "PIT Incidents YTD",
    "combined_damage": "Property & Equipment Damage YTD",
}
MEASURE_LABELS = {
    "trir": "TRIR",
    "first_aid": "First Aid",
    "lopc": "LOPC",
    "property_equipment_damage": "Property & Equipment Damage",
}


class ThroughMonth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    through: int | None = Field(default=None, ge=1, le=12)


def _year(ctx: ReportContext) -> int:
    assert ctx.period.year is not None  # noqa: S101 - "year" periods always have one
    return ctx.period.year


def _through(ctx: ReportContext) -> int | None:
    f = ctx.filters
    return f.through if isinstance(f, ThroughMonth) else None


def _ytd_label(year: int, through: int | None) -> str:
    if not through:
        return f"{year} · not started"
    if through == 12:
        return f"{year} · Jan – Dec {year}"
    last = calendar.monthrange(year, through)[1]
    return f"Year to Date · Jan 1 – {calendar.month_abbr[through]} {last}, {year}"


def _ytd_file(year: int, through: int | None) -> str:
    return str(year) if through == 12 else f"{year}-YTD"


def _through_filter(through: int | None, requested: int | None) -> list[tuple[str, str]]:
    if requested is None:
        return [("Through", f"{calendar.month_name[through]} (latest)" if through else "Latest")]
    return [("Through", calendar.month_name[requested])]


def _monthly_columns(months: int, first: str = "Measure") -> list[Column]:
    return [
        Column(first, "text", 34),
        *(Column(MONTHS[m], "int", 7) for m in range(months)),
        Column("Total", "int", 9),
    ]


def _series_row(series: AnalyticsSeriesOut | AnalyticsCategoryOut) -> list[Value]:
    return [series.name, *series.values, series.total]


def _breakdown_table(breakdown: AnalyticsBreakdownOut, months: int, sheet: str) -> Table:
    note = (
        " Tags are not exclusive: totals can exceed the events they describe."
        if (breakdown.is_tag)
        else ""
    )
    return Table(
        breakdown.name,
        _monthly_columns(months, "Category"),
        [_series_row(row) for row in breakdown.rows],
        description=f"Unreported months are blank, not zero.{note}",
        sheet=sheet,
    )


def _totals_chart(title: str, rows: list[AnalyticsCategoryOut], color: str) -> Chart:
    present = [r for r in rows if r.total is not None]
    return Chart(
        title,
        [r.name for r in present],
        [Series("Count", [r.total for r in present], color)],
        kind="hbar",
        x_label="Category",
    )


# --- Incident & Near Miss -----------------------------------------------------


def build_incidents(ctx: ReportContext) -> ReportContent:
    year, requested = _year(ctx), _through(ctx)
    try:
        data = analytics.load_analytics(
            DatabaseSafetyMetricsRepository(ctx.session),
            year=year,
            through_month=requested,
            now=ctx.now,
            behavior=DatabaseBehaviorRepository(ctx.session),
        )
    except MonthNotStartedError:
        raise ReportInputError(
            "The report cannot run through a month that has not started."
        ) from None
    through = data.through_month
    months = through or 0
    labels = MONTHS[:months]
    kpis = []
    for kpi in data.kpis:
        caption = f"{kpi.months_reported} of {months} months reported"
        if kpi.prior_year is not None and kpi.prior_year.value is not None:
            caption += f" · {kpi.prior_year.year}: {kpi.prior_year.value}"
        kpis.append(Kpi(KPI_LABELS.get(kpi.key, kpi.key), kpi.value, caption=caption))
    series_rows = [
        data.incidents,
        data.near_misses,
        *data.classifications,
        data.lopc,
        data.pit,
        data.property_damage,
        data.equipment_damage,
    ]
    charts = [
        Chart(
            "Incidents and near misses by month",
            labels,
            [
                Series("Incidents", data.incidents.values, BLUE),
                Series("Near misses", data.near_misses.values, AMBER),
            ],
            x_label="Month",
            y_label="Count",
        ),
    ]
    if data.incidents_prior_year_available:
        charts.append(
            Chart(
                f"Incidents: {year} vs {data.prior_year}",
                labels,
                [
                    Series(str(year), data.incidents.values, BLUE),
                    Series(str(data.prior_year), data.incidents_prior_year_monthly.values, SLATE),
                ],
                x_label="Month",
            )
        )
    charts += [
        _totals_chart("Incidents by area", data.incidents_by_area, BLUE),
        _totals_chart("Near misses by area", data.near_misses_by_area, AMBER),
        Chart(
            "Incident classifications",
            [c.name for c in data.classifications if c.total],
            [Series("Count", [c.total for c in data.classifications if c.total], VIOLET)],
            kind="hbar",
            description="Classifications are not exclusive and are never summed.",
        ),
        Chart("LOPC by month", labels, [Series("LOPC", data.lopc.values, VIOLET)], x_label="Month"),
        _totals_chart("Near miss potential", data.near_miss_potential.categories, AMBER),
        _totals_chart("Near miss cause", data.near_miss_cause.categories, AMBER),
        _totals_chart("Injury cause", data.injury_cause.categories, RED),
        _totals_chart("Body part", data.body_part.categories, RED),
    ]
    behavior = data.behavior
    if behavior.available:
        charts.append(
            Chart(
                f"Behavior Pareto, {behavior.year}",
                [c.name for c in behavior.categories],
                [Series("Tags", [c.count for c in behavior.categories], TEAL)],
                kind="hbar",
                description="Behavior is recorded per year.",
            )
        )
    tables = [
        Table(
            "Monthly values",
            _monthly_columns(months),
            [_series_row(s) for s in series_rows],
            description="Unreported months are blank, not zero.",
            sheet="Monthly Values",
        ),
        Table(
            "Incidents by area and month",
            _monthly_columns(months, "Area"),
            [_series_row(a) for a in data.incident_area_monthly],
            sheet="Incidents by Area",
        ),
        Table(
            "Near misses by area and month",
            _monthly_columns(months, "Area"),
            [_series_row(a) for a in data.near_miss_area_monthly],
            sheet="Near Misses by Area",
        ),
        _breakdown_table(data.near_miss_potential, months, "Near Miss Potential"),
        _breakdown_table(data.near_miss_cause, months, "Near Miss Cause"),
        _breakdown_table(data.injury_cause, months, "Injury Cause"),
        _breakdown_table(data.body_part, months, "Body Part"),
        _breakdown_table(data.lopc_contributing_factors.breakdown, months, "LOPC Factors"),
    ]
    if behavior.available:
        tables.append(
            Table(
                f"Behavior Pareto, {behavior.year}",
                [
                    Column("Behavior", "text", 34),
                    Column("Tags", "int", 8),
                    Column("Share of tags", "percent", 12),
                    Column("Share of incident reports", "percent", 14),
                    Column("Cumulative share", "percent", 12),
                ],
                [
                    [
                        c.name,
                        c.count,
                        c.share_of_tags,
                        c.share_of_incident_reports,
                        c.cumulative_share_of_tags,
                    ]
                    for c in behavior.categories
                ],
                sheet="Behavior",
            )
        )
    return ReportContent(
        filters=_through_filter(through, requested),
        subtitle="Incident & Near Miss",
        period_label=_ytd_label(year, through),
        filename_period=_ytd_file(year, through),
        kpis=kpis,
        charts=charts,
        tables=tables,
        notes=[
            "Unreported months are shown blank and are never counted as zero.",
            "LOPC is the LOPC series; Spill / Release records the same events and is not "
            "added to it. PIT is the Powered Industrial Vehicle Accident classification.",
        ],
    )


# --- Safety Performance -------------------------------------------------------


def _rate(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _rate_caption(rate: RateOut) -> str:
    if rate.available and rate.hours is not None:
        return f"{rate.events} events / {rate.hours:,.0f} hours"
    blocked = ", ".join(f"{calendar.month_abbr[m.month]} {m.year}" for m in rate.ineligible_months)
    return f"Not available; ineligible months: {blocked}" if blocked else "Not available"


def build_performance(ctx: ReportContext) -> ReportContent:
    year, requested = _year(ctx), _through(ctx)
    data = performance_service.dashboard(
        DatabasePerformanceRepository(ctx.session), year, through_month=requested, now=ctx.now
    )
    through = data.through_month
    kpis = [Kpi("YTD hours", _rate(data.ytd_hours), "decimal")]
    for kpi in data.kpis:
        label = MEASURE_LABELS.get(kpi.measure, kpi.measure)
        for name, rate in (("YTD", kpi.ytd), ("12MRA", kpi.rolling)):
            kpis.append(
                Kpi(f"{label} · {name}", _rate(rate.rate), "decimal", caption=_rate_caption(rate))
            )
    charts = [
        Chart(
            f"{MEASURE_LABELS.get(t.measure, t.measure)} rate",
            MONTHS,
            [
                Series("YTD", [_rate(v) for v in t.ytd], BLUE),
                Series("12MRA", [_rate(v) for v in t.rolling], AMBER),
            ],
            kind="line",
            value_type="decimal",
            x_label="Month",
        )
        for t in data.trends
    ]
    annual = [a for a in data.annual_trir if a.rate is not None]
    charts.append(
        Chart(
            "Annual TRIR",
            [str(a.year) for a in annual],
            [Series("TRIR", [_rate(a.rate) for a in annual], BLUE)],
            value_type="decimal",
            x_label="Year",
        )
    )
    months = [
        [
            calendar.month_name[m.month],
            m.status.replace("_", " ").capitalize(),
            _rate(m.hours.total_hours) if m.hours else None,
            _rate(m.hours.hourly_hours) if m.hours else None,
            _rate(m.hours.salary_hours) if m.hours else None,
            m.counts.trir,
            m.counts.first_aid,
            m.counts.lopc,
            m.counts.property_equipment_damage,
            "Yes" if m.eligible else "No",
        ]
        for m in data.months
    ]
    rates = [
        [
            MEASURE_LABELS.get(k.measure, k.measure),
            _rate(k.ytd.rate),
            k.ytd.events,
            _rate(k.ytd.hours),
            _rate(k.rolling.rate),
            k.rolling.events,
            _rate(k.rolling.hours),
            f"{calendar.month_abbr[k.rolling.start.month]} {k.rolling.start.year} – "
            f"{calendar.month_abbr[k.rolling.end.month]} {k.rolling.end.year}",
        ]
        for k in data.kpis
    ]
    return ReportContent(
        filters=_through_filter(through, requested),
        subtitle="Rates per 200,000 hours worked: year to date and 12-month rolling average",
        period_label=_ytd_label(year, through),
        filename_period=_ytd_file(year, through),
        kpis=kpis,
        charts=charts,
        tables=[
            Table(
                "Rates",
                [
                    Column("Measure", "text", 28),
                    Column("YTD rate", "decimal", 10),
                    Column("YTD events", "int", 10),
                    Column("YTD hours", "decimal", 14),
                    Column("12MRA rate", "decimal", 10),
                    Column("12MRA events", "int", 10),
                    Column("12MRA hours", "decimal", 14),
                    Column("12MRA window", "text", 22),
                ],
                rates,
                sheet="Rates",
            ),
            Table(
                "Months",
                [
                    Column("Month", "text", 12),
                    Column("Status", "text", 12),
                    Column("Total hours", "decimal", 14),
                    Column("Hourly hours", "decimal", 14),
                    Column("Salary hours", "decimal", 14),
                    Column("TRIR events", "int", 10),
                    Column("First aid", "int", 10),
                    Column("LOPC", "int", 8),
                    Column("Property & equipment damage", "int", 12),
                    Column("Eligible", "text", 9),
                ],
                months,
                description="A month counts toward rates once it is closed.",
                sheet="Months",
            ),
            Table(
                "Annual TRIR",
                [
                    Column("Year", "text", 8),
                    Column("Basis", "text", 16),
                    Column("Partial", "text", 8),
                    Column("Events", "int", 8),
                    Column("Hours", "decimal", 14),
                    Column("TRIR", "decimal", 10),
                ],
                [
                    [
                        str(a.year),
                        (a.basis or "").replace("_", " "),
                        "Yes" if a.partial else "No",
                        a.events,
                        _rate(a.hours),
                        _rate(a.rate),
                    ]
                    for a in data.annual_trir
                ],
                sheet="Annual TRIR",
            ),
        ],
    )


# --- TRIR Experience ----------------------------------------------------------


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def build_trir(ctx: ReportContext) -> ReportContent:
    year, requested = _year(ctx), _through(ctx)
    data = _experience(ctx.session, year, requested)
    current, rolling = data.current, data.rolling12
    through = data.status.through_month
    history = sorted(data.history, key=lambda h: h.year)
    return ReportContent(
        filters=_through_filter(through, requested),
        subtitle="Total Recordable Incident Rate per 200,000 hours worked",
        period_label=_ytd_label(year, through),
        filename_period=_ytd_file(year, through),
        kpis=[
            Kpi(
                "TRIR YTD",
                _dec(current.rate),
                "decimal",
                caption=current.unavailable_reason or (current.formula or ""),
            ),
            Kpi(
                "TRIR 12-month rolling",
                _dec(rolling.rate),
                "decimal",
                caption=rolling.unavailable_reason or (rolling.formula or ""),
            ),
            Kpi("Recordables YTD", current.recordables),
            Kpi("Hours YTD", _rate(current.hours), "decimal"),
            Kpi(
                "Benchmark",
                _dec(data.comparison.benchmark),
                "decimal",
                caption=data.comparison.statement,
            ),
        ],
        charts=[
            Chart(
                "TRIR by year",
                [str(h.year) for h in history],
                [
                    Series("LCY TRIR", [_dec(h.calculation.rate) for h in history], BLUE),
                    Series(
                        "Benchmark",
                        [_dec(h.benchmark.value) if h.benchmark else None for h in history],
                        SLATE,
                    ),
                ],
                value_type="decimal",
                x_label="Year",
            ),
            Chart(
                f"YTD TRIR by month, {year}",
                MONTHS,
                [Series("YTD TRIR", [_dec(m.ytd_rate) for m in data.monthly], BLUE)],
                kind="line",
                value_type="decimal",
                x_label="Month",
            ),
        ],
        tables=[
            Table(
                "Monthly detail",
                [
                    Column("Month", "text", 12),
                    Column("State", "text", 18),
                    Column("Recordables", "int", 10),
                    Column("Hours", "decimal", 14),
                    Column("YTD recordables", "int", 12),
                    Column("YTD hours", "decimal", 14),
                    Column("YTD TRIR", "decimal", 10),
                ],
                [
                    [
                        calendar.month_name[m.month],
                        m.state.replace("_", " "),
                        m.recordables,
                        _rate(m.hours),
                        m.ytd_recordables,
                        _rate(m.ytd_hours),
                        _dec(m.ytd_rate),
                    ]
                    for m in data.monthly
                ],
                sheet="Monthly",
            ),
            Table(
                "History",
                [
                    Column("Year", "text", 8),
                    Column("TRIR", "decimal", 10),
                    Column("Recordables", "int", 10),
                    Column("Hours", "decimal", 14),
                    Column("Benchmark", "decimal", 10),
                    Column("Comparison", "text", 40),
                    Column("Partial", "text", 8),
                    Column("Note", "text", 40),
                ],
                [
                    [
                        str(h.year),
                        _dec(h.calculation.rate),
                        h.calculation.recordables,
                        _rate(h.calculation.hours),
                        _dec(h.benchmark.value) if h.benchmark else None,
                        h.comparison.statement,
                        "Yes" if h.partial else "No",
                        h.note,
                    ]
                    for h in history
                ],
                sheet="History",
            ),
        ],
        notes=[f"{d.check}: {d.message}" for d in data.data_quality if d.status == "warning"]
        + [f"Formula: {data.methodology.formula}", f"Rounding: {data.methodology.rounding}"],
    )


# --- Safety Observations -------------------------------------------------------


def build_observations(ctx: ReportContext) -> ReportContent:
    year = _year(ctx)
    data = observation_service.dashboard(
        DatabaseObservationRepository(ctx.session), year=year, today=ctx.today
    )
    c = data.counts
    through = data.through_month
    labels = MONTHS[:through]
    started = [m for m in data.months if m.counts is not None]
    count_columns = [
        Column("Total", "int", 8),
        Column("Safe", "int", 8),
        Column("Unsafe", "int", 8),
        Column("Safe acts", "int", 9),
        Column("Safe conditions", "int", 10),
        Column("Unsafe acts", "int", 9),
        Column("Unsafe conditions", "int", 10),
    ]
    return ReportContent(
        filters=[],
        period_label=_ytd_label(year, through) if through < 12 else str(year),
        filename_period=_ytd_file(year, through),
        kpis=[
            Kpi("Observations", c.total),
            Kpi("Safe", c.safe),
            Kpi("Unsafe", c.unsafe),
            Kpi("Unsafe share", _rate(data.unsafe_share), "percent"),
            Kpi("Safe acts", c.safe_act),
            Kpi("Safe conditions", c.safe_condition),
            Kpi("Unsafe acts", c.unsafe_act),
            Kpi("Unsafe conditions", c.unsafe_condition),
        ],
        charts=[
            Chart(
                "Observations by month",
                labels,
                [
                    Series("Safe", [m.counts.safe if m.counts else None for m in started], GREEN),
                    Series("Unsafe", [m.counts.unsafe if m.counts else None for m in started], RED),
                ],
                x_label="Month",
            ),
            Chart(
                "Observations by category",
                [k.name for k in data.categories if k.total],
                [
                    Series("Safe", [k.safe for k in data.categories if k.total], GREEN),
                    Series("Unsafe", [k.unsafe for k in data.categories if k.total], RED),
                ],
                kind="hbar",
            ),
        ],
        tables=[
            Table(
                "Observations by month",
                [Column("Month", "text", 12), *count_columns],
                [
                    [
                        calendar.month_name[m.month],
                        m.counts.total,
                        m.counts.safe,
                        m.counts.unsafe,
                        m.counts.safe_act,
                        m.counts.safe_condition,
                        m.counts.unsafe_act,
                        m.counts.unsafe_condition,
                    ]
                    for m in started
                    if m.counts
                ],
                sheet="By Month",
            ),
            Table(
                "Observations by category",
                [
                    Column("Category", "text", 30),
                    Column("Total", "int", 8),
                    Column("Safe", "int", 8),
                    Column("Unsafe", "int", 8),
                    *(Column(MONTHS[i], "int", 7) for i in range(through)),
                ],
                [
                    [k.name, k.total, k.safe, k.unsafe, *k.monthly[:through]]
                    for k in data.categories
                ],
                sheet="By Category",
                pdf_columns=[0, 1, 2, 3],
            ),
        ],
    )


INCIDENTS = ReportDefinition(
    key="safety-incidents",
    title="Incident & Near Miss Dashboard",
    module=MODULE,
    filename="Safety-Incidents",
    view_permissions=(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW),
    export_permission=Permission.SAFETY_RECORD_EXPORT,
    filters=ThroughMonth,
    period_modes=YEAR_ONLY,
    build=build_incidents,
)

PERFORMANCE = ReportDefinition(
    key="safety-performance",
    title="Safety Performance Dashboard",
    module=MODULE,
    filename="Safety-Performance",
    view_permissions=(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW),
    export_permission=Permission.SAFETY_RECORD_EXPORT,
    filters=ThroughMonth,
    period_modes=YEAR_ONLY,
    build=build_performance,
)

TRIR = ReportDefinition(
    key="safety-trir",
    title="TRIR Experience",
    module=MODULE,
    filename="TRIR",
    view_permissions=(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW),
    export_permission=Permission.SAFETY_RECORD_EXPORT,
    filters=ThroughMonth,
    period_modes=YEAR_ONLY,
    build=build_trir,
)

OBSERVATIONS = ReportDefinition(
    key="safety-observations",
    title="Safety Observations Dashboard",
    module=MODULE,
    filename="Safety-Observations",
    view_permissions=(Permission.SAFETY_OBSERVATION_VIEW, Permission.SAFETY_DASHBOARD_VIEW),
    export_permission=Permission.SAFETY_OBSERVATION_EXPORT,
    filters=NoFilters,
    period_modes=YEAR_ONLY,
    build=build_observations,
)
