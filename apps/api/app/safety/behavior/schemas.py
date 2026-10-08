from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator

from app.core.schemas import CamelModel
from app.safety.schemas import MonthlyCount, ReportingYear

# An annual count has the same strict bounds as a monthly one.
AnnualCount = MonthlyCount
MAX_BEHAVIOR_CHANGES = 200


class BehaviorCountRow(CamelModel):
    id: int
    code: str
    name: str
    value: int | None = Field(description="Annual count; null when unreported.")


class BehaviorCountsResponse(CamelModel):
    """Annual Behavior tag counts for one year, every active category in display order."""

    year: int
    can_edit: bool
    categories: list[BehaviorCountRow]
    total: int | None = Field(description="Sum of reported categories; null when none.")
    years_with_data: list[int]


class BehaviorChange(CamelModel):
    """Set one category's annual count; ``value`` null clears it (unreported).
    ``previous_value`` is the value the client loaded (see ``CellChange``)."""

    model_config = ConfigDict(extra="forbid")

    category_id: Annotated[int, Field(strict=True, ge=1)]
    value: AnnualCount | None
    previous_value: AnnualCount | None


class SaveBehaviorCountsRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: ReportingYear
    changes: Annotated[list[BehaviorChange], Field(min_length=1, max_length=MAX_BEHAVIOR_CHANGES)]

    @model_validator(mode="after")
    def _categories_are_unique(self) -> Self:
        ids = [change.category_id for change in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("each category may appear only once per save")
        return self


class SaveBehaviorCountsResponse(CamelModel):
    changed_categories: int
    counts: BehaviorCountsResponse


class BehaviorConflict(CamelModel):
    category_id: int
    current_value: int | None
