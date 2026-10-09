import datetime as dt
import re
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BeforeValidator, ConfigDict, Field

from app.core.schemas import CamelModel
from app.safety.observations.models import (
    EARLIEST_OBSERVED_ON,
    MAX_AREA_LOCATION_LENGTH,
    MAX_NOTE_LENGTH,
)

Outcome = Literal["safe", "unsafe"]
Kind = Literal["act", "condition"]


def _blank_is_none(value: Any) -> Any:
    """Trim optional text; blank text means "not provided" and is stored as NULL."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


AreaLocation = Annotated[
    Annotated[str, Field(max_length=MAX_AREA_LOCATION_LENGTH)] | None,
    BeforeValidator(_blank_is_none),
]
Note = Annotated[
    Annotated[str, Field(max_length=MAX_NOTE_LENGTH)] | None, BeforeValidator(_blank_is_none)
]


def _iso_date_only(value: Any) -> Any:
    """Accept "YYYY-MM-DD" only; timestamps, numbers, and other date formats are rejected."""
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise ValueError("expected a date as YYYY-MM-DD")


ObservedOn = Annotated[dt.date, BeforeValidator(_iso_date_only), Field(ge=EARLIEST_OBSERVED_ON)]
CategoryId = Annotated[int, Field(strict=True, ge=1)]


class ObservationCategoryOut(CamelModel):
    id: int
    code: str
    name: str


class ObservationCategoriesResponse(CamelModel):
    """Active categories, in display order, for choosing a category."""

    categories: list[ObservationCategoryOut]
    can_edit: bool
    can_create: bool = False
    can_delete: bool = False


class ObservationInput(CamelModel):
    """One observation. Optional text omitted, null, or blank is stored as NULL."""

    model_config = ConfigDict(extra="forbid")

    observed_on: ObservedOn
    outcome: Outcome
    kind: Kind
    category_id: CategoryId
    area_location: AreaLocation = None
    description: Note = None
    corrective_action: Note = None


class ObservationUpdate(ObservationInput):
    """Replaces every field. ``expected_updated_at`` is the ``updatedAt`` the
    client loaded; the update is refused if the observation changed since."""

    expected_updated_at: AwareDatetime


class ObservationOut(CamelModel):
    id: int
    observed_on: dt.date
    outcome: Outcome
    kind: Kind
    category_id: int
    category_code: str
    category_name: str
    area_location: str | None
    description: str | None
    corrective_action: str | None
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


class ObservationListResponse(CamelModel):
    """Newest observed date first, then newest entry first."""

    observations: list[ObservationOut]
    total_matching: int
    can_edit: bool
    can_create: bool = False
    can_delete: bool = False


class ObservationCounts(CamelModel):
    """Counts of observation records. Every figure counts the same rows."""

    total: int
    safe: int
    unsafe: int
    safe_act: int
    safe_condition: int
    unsafe_act: int
    unsafe_condition: int


class CategoryCount(CamelModel):
    category_id: int
    code: str
    name: str
    total: int
    safe: int
    unsafe: int


class ObservationSummaryResponse(CamelModel):
    """Counts for a reporting period: a year, or one month of it."""

    year: int
    month: int | None
    counts: ObservationCounts
    categories: list[CategoryCount]


class DashboardMonth(CamelModel):
    month: int
    counts: ObservationCounts | None = Field(
        description="Null for months that have not started yet."
    )


class DashboardCategory(CategoryCount):
    monthly: list[int | None] = Field(
        description="12 entries, January first; null for months that have not started yet."
    )


class ObservationDashboardResponse(CamelModel):
    year: int
    through_month: int = Field(
        description="Last month of the year that has started (0-12). Later months are null."
    )
    counts: ObservationCounts
    unsafe_share: float | None = Field(
        description="Unsafe / total for the year; null when there are no observations."
    )
    months: list[DashboardMonth]
    categories: list[DashboardCategory]
    years_with_data: list[int]
