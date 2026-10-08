"""Safety Performance: monthly hours entry and calculated rates.

Hours changes and month closes are audited as ``safety.performance_hours``
with key ``performance-hours/YYYY-MM``. Months are the Baytown site's calendar
months (``site_today``): hours can be entered once a month has started and the
month closed once it has ended.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.audit.recorder import AuditAction, AuditChange
from app.safety.performance.calculations import (
    INCIDENTS,
    AnnualLegacy,
    Measure,
    MonthCounts,
    MonthHours,
    Period,
    WindowResult,
    annual_trir,
    count_source,
    ineligible_reason,
    latest_ytd_month,
    month_counts,
    rolling_window,
    window_rate,
    ytd_window,
)
from app.safety.performance.repository import (
    HoursRecord,
    HoursValues,
    PerformanceRepository,
)
from app.safety.performance.schemas import (
    AnnualTrirOut,
    HoursOut,
    IneligibleMonthOut,
    KpiOut,
    MonthCountsOut,
    MonthOut,
    PerformanceDashboardResponse,
    PerformanceYearResponse,
    PeriodOut,
    RateOut,
    RateTrendOut,
    SaveMonthHoursRequest,
)
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

HOURS_ENTITY_TYPE = "safety.performance_hours"
ANNUAL_ENTITY_TYPE = "safety.performance_annual_legacy"


class PerformanceRuleError(ValueError):
    """The change breaks a Safety Performance rule. Nothing was written."""

    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


class EditConflictError(RuntimeError):
    """The month changed since the client loaded it. Nothing was written."""

    def __init__(self, current: HoursRecord | None) -> None:
        super().__init__("month changed since it was loaded")
        self.current = current


def hours_key(year: int, month: int) -> str:
    return f"performance-hours/{year:04d}-{month:02d}"


def annual_key(year: int) -> str:
    return f"performance-annual-legacy/{year:04d}"


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def hours_audit_value(values: HoursValues) -> dict[str, Any]:
    return {
        "total_hours": _decimal_text(values.total_hours),
        "hourly_hours": _decimal_text(values.hourly_hours),
        "salary_hours": _decimal_text(values.salary_hours),
        "month_closed": values.month_closed,
    }


def normalized(values: HoursValues) -> HoursValues:
    # Compare and audit at the stored scale, so 100 and 100.00 are the same value.
    cent = Decimal("0.01")

    def scale(value: Decimal | None) -> Decimal | None:
        return None if value is None else value.quantize(cent)

    return HoursValues(
        total_hours=values.total_hours.quantize(cent),
        hourly_hours=scale(values.hourly_hours),
        salary_hours=scale(values.salary_hours),
        month_closed=values.month_closed,
    )


def _month_started(year: int, month: int, today: dt.date) -> bool:
    return (year, month) <= (today.year, today.month)


def _month_ended(year: int, month: int, today: dt.date) -> bool:
    return (year, month) < (today.year, today.month)


def _log(event: str, *, year: int, month: int, actor_id: str, change_set: uuid.UUID) -> None:
    logger.info(
        "event=%s key=%s user=%s change_set=%s",
        event,
        hours_key(year, month),
        actor_id,
        change_set,
    )


def save_month(
    repository: PerformanceRepository,
    year: int,
    month: int,
    request: SaveMonthHoursRequest,
    *,
    actor_id: str,
    now: dt.datetime,
) -> HoursRecord:
    """Create or replace one month's hours and closed status (audited).

    Raises PerformanceRuleError or EditConflictError; nothing is written then.
    """
    today = site_today(now)
    if not _month_started(year, month, today):
        raise PerformanceRuleError(
            "month_not_started", "Hours cannot be entered for a month that has not started."
        )
    if request.month_closed and not _month_ended(year, month, today):
        raise PerformanceRuleError(
            "month_not_ended", "A month can be closed only after it has ended."
        )
    values = normalized(
        HoursValues(
            total_hours=request.total_hours,
            hourly_hours=request.hourly_hours,
            salary_hours=request.salary_hours,
            month_closed=request.month_closed,
        )
    )

    try:
        repository.lock_month(year, month)
        current = repository.get_hours(year, month)
        if (current.updated_at if current else None) != request.expected_updated_at:
            raise EditConflictError(current)
        if current is not None and current.values == values:
            repository.rollback()
            return current

        action: AuditAction
        if current is None:
            action = "create"
            repository.insert_hours(year, month, values, actor_id=actor_id, at=now)
        else:
            action = "update"
            repository.update_hours(year, month, values, actor_id=actor_id, at=now)
        change_set = uuid.uuid4()
        repository.record_audit(
            [
                AuditChange(
                    action=action,
                    entity_type=HOURS_ENTITY_TYPE,
                    entity_key=hours_key(year, month),
                    old_value=hours_audit_value(current.values) if current else None,
                    new_value=hours_audit_value(values),
                )
            ],
            actor_id=actor_id,
            change_set_id=change_set,
            at=now,
        )
        saved = repository.get_hours(year, month)
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    assert saved is not None  # noqa: S101 - written in this transaction
    _log(
        "safety_performance_hours_saved",
        year=year,
        month=month,
        actor_id=actor_id,
        change_set=change_set,
    )
    return saved


def clear_month(
    repository: PerformanceRepository,
    year: int,
    month: int,
    *,
    expected_updated_at: dt.datetime,
    actor_id: str,
    now: dt.datetime,
) -> None:
    """Remove a month's hours, returning it to Not Reported (audited)."""
    try:
        repository.lock_month(year, month)
        current = repository.get_hours(year, month)
        if current is None or current.updated_at != expected_updated_at:
            raise EditConflictError(current)
        repository.delete_hours(year, month)
        change_set = uuid.uuid4()
        repository.record_audit(
            [
                AuditChange(
                    action="delete",
                    entity_type=HOURS_ENTITY_TYPE,
                    entity_key=hours_key(year, month),
                    old_value=hours_audit_value(current.values),
                    new_value=None,
                )
            ],
            actor_id=actor_id,
            change_set_id=change_set,
            at=now,
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log(
        "safety_performance_hours_cleared",
        year=year,
        month=month,
        actor_id=actor_id,
        change_set=change_set,
    )


# Reading ---------------------------------------------------------------------------


class _Facts:
    """Hours and counts for the months a response needs."""

    def __init__(self, repository: PerformanceRepository, years: Collection[int]) -> None:
        self.records = repository.hours()
        self.hours: dict[Period, MonthHours] = {
            period: MonthHours(r.values.total_hours, r.values.month_closed)
            for period, r in self.records.items()
        }
        wanted = set(years) | {period[0] for period in self.records}
        incidents, legacy = repository.counts(wanted)
        self.counts: dict[Period, MonthCounts] = {}
        for year in wanted:
            source = count_source(year)
            stored = incidents if source == INCIDENTS else legacy
            for month in range(1, 13):
                record = self.records.get((year, month))
                closed = record is not None and record.values.month_closed
                self.counts[(year, month)] = month_counts(
                    source, stored.get((year, month), {}), closed=closed
                )
        self.years_with_data = sorted({period[0] for period in self.records}, reverse=True)


@dataclass(frozen=True)
class TrirInputs:
    """The Safety Performance facts a TRIR is calculated from: monthly worked
    hours (``total_hours``), monthly TRIR numerators (``MonthCounts.trir``) and
    the annual legacy rows. Read-only; TRIR Experience stores no hours."""

    hours: dict[Period, MonthHours]
    counts: dict[Period, MonthCounts]
    annual_legacy: dict[int, AnnualLegacy]


def trir_inputs(repository: PerformanceRepository, years: Collection[int]) -> TrirInputs:
    facts = _Facts(repository, years)
    legacy = {
        y: AnnualLegacy(r.values.recordables, r.values.total_hours)
        for y, r in repository.annual_legacy().items()
    }
    return TrirInputs(facts.hours, facts.counts, legacy)


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def hours_out(record: HoursRecord) -> HoursOut:
    return HoursOut(
        total_hours=float(record.values.total_hours),
        hourly_hours=_float(record.values.hourly_hours),
        salary_hours=_float(record.values.salary_hours),
        month_closed=record.values.month_closed,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
    )


def _counts_out(counts: MonthCounts) -> MonthCountsOut:
    return MonthCountsOut(
        trir=counts.trir,
        first_aid=counts.first_aid,
        lopc=counts.lopc,
        property_equipment_damage=counts.property_equipment_damage,
        recordable_injury=counts.recordable_injury,
        occupational_illness=counts.occupational_illness,
        property_damage=counts.property_damage,
        equipment_damage_failure=counts.equipment_damage_failure,
    )


def _months(facts: _Facts, year: int, today: dt.date) -> list[MonthOut]:
    months = []
    for month in range(1, 13):
        record = facts.records.get((year, month))
        reason = ineligible_reason(facts.hours.get((year, month)))
        counts = facts.counts[(year, month)]
        if record is None:
            status = "not_reported"
        elif record.values.month_closed:
            status = "closed"
        else:
            status = "reported"
        months.append(
            MonthOut(
                month=month,
                status=status,
                hours=hours_out(record) if record else None,
                counts=_counts_out(counts),
                counts_confirmed=counts.confirmed,
                eligible=reason is None,
                ineligible_reason=reason,
                can_enter=_month_started(year, month, today),
                can_close=_month_ended(year, month, today),
            )
        )
    return months


def year_view(
    repository: PerformanceRepository, year: int, *, can_edit: bool, now: dt.datetime
) -> PerformanceYearResponse:
    facts = _Facts(repository, [year])
    return PerformanceYearResponse(
        year=year,
        count_source=count_source(year),
        can_edit=can_edit,
        months=_months(facts, year, site_today(now)),
        years_with_data=facts.years_with_data,
    )


def _period(period: Period) -> PeriodOut:
    return PeriodOut(year=period[0], month=period[1])


def rate_out(result: WindowResult) -> RateOut:
    return RateOut(
        measure=result.measure,
        start=_period(result.start),
        end=_period(result.end),
        available=result.available,
        ineligible_months=[
            IneligibleMonthOut(year=m.period[0], month=m.period[1], reason=m.reason)
            for m in result.ineligible
        ],
        events=result.events,
        hours=_float(result.hours),
        rate=result.rate,
        property_damage=result.property_damage,
        equipment_damage_failure=result.equipment_damage_failure,
    )


def dashboard(
    repository: PerformanceRepository,
    year: int,
    *,
    through_month: int | None,
    now: dt.datetime,
) -> PerformanceDashboardResponse:
    legacy = {
        y: AnnualLegacy(r.values.recordables, r.values.total_hours)
        for y, r in repository.annual_legacy().items()
    }
    # Annual history runs from the earliest year with any record to this year.
    first_year = min([*legacy, year - 1])
    facts = _Facts(repository, range(first_year, year + 1))
    hours, counts = facts.hours, facts.counts
    first_year = min([first_year, *(period[0] for period in hours)])
    through = through_month if through_month is not None else latest_ytd_month(year, hours)

    kpis: list[KpiOut] = []
    ytd_hours = None
    if through is not None:
        end = (year, through)
        for measure in Measure:
            ytd = window_rate(measure, ytd_window(end), hours, counts)
            rolling = window_rate(measure, rolling_window(end), hours, counts)
            kpis.append(KpiOut(measure=measure, ytd=rate_out(ytd), rolling=rate_out(rolling)))
        ytd_hours = _float(window_rate(Measure.TRIR, ytd_window(end), hours, counts).hours)

    trends = []
    for measure in Measure:
        ytd_series: list[float | None] = []
        rolling_series: list[float | None] = []
        for month in range(1, 13):
            end = (year, month)
            ytd_series.append(window_rate(measure, ytd_window(end), hours, counts).rate)
            rolling_series.append(window_rate(measure, rolling_window(end), hours, counts).rate)
        trends.append(RateTrendOut(measure=measure, ytd=ytd_series, rolling=rolling_series))

    annual = [
        AnnualTrirOut(
            year=a.year,
            basis=a.basis,
            partial=a.partial,
            through_month=a.through_month,
            events=a.events,
            hours=_float(a.hours),
            rate=a.rate,
        )
        for a in annual_trir(range(first_year, year + 1), hours, counts, legacy)
    ]
    # Leading years with no record of any kind say nothing.
    while annual and annual[0].basis is None:
        annual.pop(0)

    return PerformanceDashboardResponse(
        year=year,
        count_source=count_source(year),
        through_month=through,
        kpis=kpis,
        ytd_hours=ytd_hours,
        months=_months(facts, year, site_today(now)),
        trends=trends,
        annual_trir=annual,
        years_with_data=facts.years_with_data,
    )
