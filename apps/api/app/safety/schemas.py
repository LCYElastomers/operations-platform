from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from app.core.schemas import CamelModel
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR

# Sanity ceiling for a monthly count; rejects obvious entry errors.
MAX_MONTHLY_COUNT = 100_000
MAX_CHANGES_PER_SAVE = 2000

ReportingYear = Annotated[int, Field(strict=True, ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
ReportingMonth = Annotated[int, Field(strict=True, ge=1, le=12)]
# Strict: JSON strings, booleans, and fractional numbers are rejected, not coerced.
MonthlyCount = Annotated[int, Field(strict=True, ge=0, le=MAX_MONTHLY_COUNT)]


class MetricCategoryRow(CamelModel):
    """One grid row. ``values`` has 12 entries (Jan..Dec); null means unreported."""

    id: int
    code: str
    name: str
    description: str | None = None
    # The linked area's kind for an area category (Incidents / Near Misses by Area).
    area_kind: str | None = None
    values: list[int | None]
    ytd: int | None = Field(description="Sum of reported months; null when none are reported.")


class MetricSectionBlock(CamelModel):
    """A block of categories. Categories are not summed into a section total:
    totals such as Incident are explicit categories, and breakdowns such as
    Incident Classification are not mutually exclusive."""

    id: int
    code: str
    name: str
    categories: list[MetricCategoryRow]


class MonthlyMetricsResponse(CamelModel):
    metric_set: str
    year: int
    can_edit: bool
    sections: list[MetricSectionBlock]
    years_with_data: list[int]


class CellChange(CamelModel):
    """Set one cell. ``value`` null clears it (unreported).

    ``previous_value`` is the value the client last saw; the save is refused
    when the stored value no longer matches, so concurrent edits are never
    silently overwritten.
    """

    model_config = ConfigDict(extra="forbid")

    category_id: Annotated[int, Field(strict=True, ge=1)]
    month: ReportingMonth
    value: MonthlyCount | None
    previous_value: MonthlyCount | None


class SaveMonthlyMetricsRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: ReportingYear
    changes: Annotated[list[CellChange], Field(min_length=1, max_length=MAX_CHANGES_PER_SAVE)]

    @model_validator(mode="after")
    def _cells_are_unique(self) -> Self:
        cells = [(change.category_id, change.month) for change in self.changes]
        if len(cells) != len(set(cells)):
            raise ValueError("each category and month may appear only once per save")
        return self


class SaveMonthlyMetricsResponse(CamelModel):
    changed_cells: int
    metrics: MonthlyMetricsResponse


class CellConflict(CamelModel):
    category_id: int
    month: int
    current_value: int | None


class AnalyticsSeriesOut(CamelModel):
    """One stored category, January..through month. Null means unreported."""

    section: str
    code: str
    name: str = Field(description="The configured display name.")
    values: list[int | None] = Field(description="One entry per month, January..through month.")
    total: int | None = Field(description="Sum of reported months; null when none are reported.")
    months_reported: int
    unreported_months: list[int]
    complete: bool = Field(description="Every month January..through month is reported.")


AnalyticsKpiKey = Literal["incidents", "near_misses", "lopc", "psif", "pit", "combined_damage"]


class AnalyticsKpiPartOut(CamelModel):
    """One component of a combined KPI."""

    code: str
    name: str
    value: int | None
    complete: bool


class AnalyticsPriorYearOut(CamelModel):
    """The same months of the previous year."""

    year: int
    value: int | None
    months_reported: int
    complete: bool
    # value(selected year) - value(prior year); null unless both are reported.
    delta: int | None


class AnalyticsKpiOut(CamelModel):
    key: AnalyticsKpiKey
    value: int | None
    months_reported: int = Field(
        description="Months January..through month reported; for a combined KPI, months "
        "every part reported."
    )
    through_month: int | None
    complete: bool
    # The components of a combined KPI (combined_damage); empty otherwise.
    parts: list[AnalyticsKpiPartOut] = Field(default_factory=list)
    # Set only for a KPI with a prior-year monthly source that has a reported month in
    # the same period (Incidents, LOPC).
    prior_year: AnalyticsPriorYearOut | None = None


ReconciliationStatus = Literal[
    "reconciled", "below_total", "above_total", "no_dimension_data", "no_authoritative_total"
]


class MonthReconciliationOut(CamelModel):
    """A breakdown's month compared with its authoritative total. Informational only:
    a difference never blocks saving and is not an error."""

    month: int
    dimension_total: int | None = Field(description="Sum of the breakdown's reported values.")
    authoritative_total: int | None
    # dimension_total - authoritative_total; null unless both are reported.
    difference: int | None
    status: ReconciliationStatus


class AnalyticsCategoryOut(CamelModel):
    """One breakdown category (an area, a tag, a factor), January..through month."""

    code: str
    name: str
    description: str | None = None
    area_kind: str | None = None
    values: list[int | None]
    total: int | None
    months_reported: int


class AnalyticsBreakdownOut(CamelModel):
    """A breakdown section. ``categories`` are sorted by total, highest first (unreported
    last), then display order; ``rows`` keep display order. Tag breakdowns may total
    more than the events they describe."""

    section: str
    name: str
    is_tag: bool = Field(description="Categories are non-exclusive tags.")
    categories: list[AnalyticsCategoryOut]
    rows: list[AnalyticsCategoryOut]
    # Per month: the sum of reported category values; null when none are reported.
    monthly_totals: list[int | None]
    total: int | None


class AnalyticsCumulativeOut(CamelModel):
    """Running totals of reported values; carried through unreported months, null before
    the first reported month."""

    code: str
    name: str
    values: list[int | None]


class LopcFactorsOut(CamelModel):
    breakdown: AnalyticsBreakdownOut
    cumulative: list[AnalyticsCumulativeOut]
    cumulative_total: list[int | None]


class AreaReconciliationOut(CamelModel):
    incidents: list[MonthReconciliationOut]
    near_misses: list[MonthReconciliationOut]


class InjuryReconciliationOut(CamelModel):
    # First Aid + Recordable Injury per month; null when neither is reported.
    injuries: list[int | None]
    injury_cause: list[MonthReconciliationOut]
    body_part: list[MonthReconciliationOut]


class BehaviorParetoRowOut(CamelModel):
    """A reported Behavior category. Shares are fractions (0.25 = 25%)."""

    code: str
    name: str
    count: int
    share_of_tags: float | None = Field(description="count / all Behavior tags.")
    share_of_incident_reports: float | None = Field(
        description="count / Incident reports. Tags overlap, so these may sum above 1."
    )
    cumulative_share_of_tags: float | None = Field(
        description="Running share of all tags in Pareto order; 1 at the last category."
    )


class BehaviorAnalyticsOut(CamelModel):
    """Annual Behavior Pareto for ``year``. Behavior is recorded per year, so the
    analytics through month does not apply to it. Behavior values are tags: their
    total need not equal the Incident total and is never reconciled with it."""

    year: int
    available: bool = Field(description="At least one category has a reported count.")
    # Reported categories, count descending, then taxonomy display order.
    categories: list[BehaviorParetoRowOut]
    # Display names of active categories with no reported count, in display order.
    unreported: list[str]
    total_tags: int | None
    # The stored Incident total for the whole year (sum of its reported months).
    incident_reports: int | None
    incident_reports_months_reported: int
    behaviors_per_incident_report: float | None


class IncidentAnalyticsResponse(CamelModel):
    """Read-only Incident & Near Miss analytics, calculated from the stored monthly values.

    Classifications are not mutually exclusive, so they are never summed or
    compared with Incident. ``combinedDamage`` is Property Damage plus Equipment
    Damage classifications, not a count of distinct events. PIT is the
    ``pit_accident`` classification and LOPC the ``lopc`` series; neither is
    added to its duplicate (``pit``, ``spill_release``).
    """

    year: int
    # January..throughMonth is covered; null when the year has not started.
    through_month: int | None
    # The latest month of the year that has started in Baytown; null for a future year.
    latest_month: int | None
    # Years the page offers, newest first.
    available_years: list[int]
    kpis: list[AnalyticsKpiOut]
    incidents: AnalyticsSeriesOut
    near_misses: AnalyticsSeriesOut
    # Incident Classification categories in display order, then PSIF.
    classifications: list[AnalyticsSeriesOut]
    lopc: AnalyticsSeriesOut
    psif: AnalyticsSeriesOut
    pit: AnalyticsSeriesOut
    property_damage: AnalyticsSeriesOut
    equipment_damage: AnalyticsSeriesOut
    combined_damage: AnalyticsSeriesOut

    # Area. The by-area lists hold areas with a reported value, highest total first;
    # the monthly lists hold every active area in display order.
    incidents_by_area: list[AnalyticsCategoryOut]
    near_misses_by_area: list[AnalyticsCategoryOut]
    incident_area_monthly: list[AnalyticsCategoryOut]
    near_miss_area_monthly: list[AnalyticsCategoryOut]
    area_reconciliation: AreaReconciliationOut

    # The same months of the previous year. Available when a month is reported.
    prior_year: int
    incidents_prior_year_monthly: AnalyticsSeriesOut
    incidents_prior_year_available: bool
    lopc_prior_year_monthly: AnalyticsSeriesOut
    lopc_prior_year_available: bool

    # Incident analysis.
    lopc_contributing_factors: LopcFactorsOut
    lopc_factor_reconciliation: list[MonthReconciliationOut]
    near_miss_potential: AnalyticsBreakdownOut
    near_miss_cause: AnalyticsBreakdownOut
    injury_cause: AnalyticsBreakdownOut
    body_part: AnalyticsBreakdownOut
    injury_reconciliation: InjuryReconciliationOut

    behavior: BehaviorAnalyticsOut
