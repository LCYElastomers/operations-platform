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


AnalyticsKpiKey = Literal["incidents", "near_misses", "lopc", "psif"]


class AnalyticsKpiOut(CamelModel):
    key: AnalyticsKpiKey
    value: int | None
    months_reported: int
    through_month: int | None
    complete: bool


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
