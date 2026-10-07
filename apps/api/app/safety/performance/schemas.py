"""Safety Performance API contract.

Hours are numbers with at most two decimal places; ``null`` is "not given" and
never zero. Rates are calculated by the API and never stored.
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, Field, StrictBool, model_validator

from app.core.schemas import CamelModel
from app.safety.performance.calculations import (
    BlockReason,
    CountSource,
    IneligibleReason,
    Measure,
)

# Far above any monthly total for one site; numeric(10, 2) allows 99,999,999.99.
MAX_MONTHLY_HOURS = Decimal(1_000_000)


def _number_only(value: Any) -> Any:
    # Booleans are ints and strings would be parsed; neither is an hours value.
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ValueError("must be a number")
    return value


Hours = Annotated[
    Decimal,
    BeforeValidator(_number_only),
    Field(ge=0, le=MAX_MONTHLY_HOURS, max_digits=10, decimal_places=2),
]


class SaveMonthHoursRequest(CamelModel):
    total_hours: Hours
    hourly_hours: Hours | None = None
    salary_hours: Hours | None = None
    month_closed: StrictBool
    # ``updatedAt`` of the month when it was loaded, or null if it had no hours.
    # The save is refused if the month changed since.
    expected_updated_at: dt.datetime | None

    @model_validator(mode="after")
    def _breakdown_adds_up(self) -> Self:
        if (
            self.hourly_hours is not None
            and self.salary_hours is not None
            and self.hourly_hours + self.salary_hours != self.total_hours
        ):
            raise ValueError("hourly and salary hours must add up to total hours")
        return self


class HoursOut(CamelModel):
    total_hours: float
    hourly_hours: float | None
    salary_hours: float | None
    month_closed: bool
    updated_at: dt.datetime
    updated_by: str


class MonthCountsOut(CamelModel):
    """Rate numerators for one month. Confirmed (closed) months have no nulls.

    ``trir`` is recordable injuries plus occupational illnesses.
    ``propertyEquipmentDamage`` is property damage plus equipment
    damage/failure. The four supporting counts are Incident & Near Miss only;
    the legacy workbook has a single recordable and a single damage count.
    """

    trir: int | None
    first_aid: int | None
    lopc: int | None
    property_equipment_damage: int | None
    recordable_injury: int | None
    occupational_illness: int | None
    property_damage: int | None
    equipment_damage_failure: int | None


MonthStatus = Literal["not_reported", "reported", "closed"]


class MonthOut(CamelModel):
    month: int
    status: MonthStatus
    hours: HoursOut | None
    counts: MonthCountsOut
    counts_confirmed: bool
    eligible: bool
    ineligible_reason: IneligibleReason | None
    # Hours can be entered once the month has started, closed once it has ended.
    can_enter: bool
    can_close: bool


class PerformanceYearResponse(CamelModel):
    year: int
    count_source: CountSource
    can_edit: bool
    months: list[MonthOut]
    years_with_data: list[int]


class PeriodOut(CamelModel):
    year: int
    month: int


class IneligibleMonthOut(PeriodOut):
    reason: BlockReason


class RateOut(CamelModel):
    measure: Measure
    start: PeriodOut
    end: PeriodOut
    available: bool
    # Every month that keeps the window from being calculated.
    ineligible_months: list[IneligibleMonthOut]
    events: int | None
    hours: float | None
    rate: float | None
    property_damage: int | None
    equipment_damage_failure: int | None


class KpiOut(CamelModel):
    measure: Measure
    ytd: RateOut
    rolling: RateOut


class RateTrendOut(CamelModel):
    measure: Measure
    # 12 entries, January..December of the year; null when unavailable.
    ytd: list[float | None]
    rolling: list[float | None]


class AnnualTrirOut(CamelModel):
    year: int
    basis: Literal["monthly", "annual_legacy"] | None
    partial: bool
    through_month: int | None
    events: int | None
    hours: float | None
    rate: float | None


class PerformanceDashboardResponse(CamelModel):
    year: int
    count_source: CountSource
    # The month the KPIs run through: the requested month, or by default the
    # latest month M for which January..M are all eligible.
    through_month: int | None
    kpis: list[KpiOut]
    ytd_hours: float | None
    months: list[MonthOut]
    trends: list[RateTrendOut]
    annual_trir: list[AnnualTrirOut]
    years_with_data: list[int]
