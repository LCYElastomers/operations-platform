from typing import Annotated, Self

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
