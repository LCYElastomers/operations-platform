"""API schemas for TRIR Experience.

Rates are sent twice: ``rate`` is the full-precision decimal as a string and
``display`` the same value rounded half-up to two decimals. Hours are numbers
(two decimals at most). No response carries a source cell or file location.
"""

from typing import Literal

from app.core.schemas import CamelModel
from app.safety.rates import Comparison

Basis = Literal["safety_performance_monthly", "historical_annual"]
MonthState = Literal["closed", "open", "not_reported", "zero_hours", "count_not_confirmed"]


class MissingMonthOut(CamelModel):
    year: int
    month: int
    reason: Literal["not_reported", "open", "zero_hours", "count_not_confirmed"]


class CalculationOut(CamelModel):
    """One TRIR with everything needed to reproduce it."""

    year: int
    basis: Basis | None
    # Calendar months covered: from_month of from_year through through_month of
    # ``year``. from_year is the year before ``year`` for a rolling 12-month window
    # that starts in it, otherwise ``year``.
    from_year: int | None
    from_month: int | None
    through_month: int | None
    recordables: int | None
    hours: float | None
    rate: str | None
    display: str | None
    formula: str | None
    numerator_source: str
    denominator_source: str
    complete: bool
    missing_months: list[MissingMonthOut]
    unavailable_reason: str | None


class BenchmarkOut(CamelModel):
    year: int
    value: str | None
    source: str | None


class ComparisonOut(CamelModel):
    benchmark_year: int | None
    benchmark: str | None
    # LCY TRIR minus the benchmark, full precision and displayed.
    difference: str | None
    difference_display: str | None
    status: Comparison
    statement: str


class HistoryRowOut(CamelModel):
    year: int
    calculation: CalculationOut
    incident_count: int | None
    legacy_trir: str | None
    legacy_tir: str | None
    # Calculated minus legacy TRIR.
    legacy_difference: str | None
    benchmark: BenchmarkOut | None
    comparison: ComparisonOut
    partial: bool
    note: str | None


class MonthDetailOut(CamelModel):
    month: int
    state: MonthState
    recordables: int | None
    hours: float | None
    ytd_recordables: int | None
    ytd_hours: float | None
    ytd_rate: str | None
    ytd_display: str | None


class DataQualityItemOut(CamelModel):
    year: int | None
    check: str
    status: Literal["ok", "warning"]
    message: str


class MethodologyOut(CamelModel):
    formula: str
    rate_base: int
    numerator: str
    denominator: str
    contractor_hours: str
    benchmark: str
    cutoff: str
    rounding: str
    comparison_tolerance: str
    historical_years: str
    unreported_months: str
    legacy_tir: str


class TrirStatusOut(CamelModel):
    year: int
    latest_complete_month: int | None
    through_month: int | None
    complete: bool
    history_years: list[int]


class TrirExperienceResponse(CamelModel):
    year: int
    status: TrirStatusOut
    current: CalculationOut
    comparison: ComparisonOut
    rolling12: CalculationOut
    incident_count: int | None
    history: list[HistoryRowOut]
    monthly: list[MonthDetailOut]
    benchmarks: list[BenchmarkOut]
    data_quality: list[DataQualityItemOut]
    methodology: MethodologyOut
