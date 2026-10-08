"""Safety Performance rate calculations. Pure functions; nothing is stored.

Every rate is ``events × 200,000 ÷ worked hours`` (``app.safety.rates``) over
one window of calendar months, and the events and the hours always come from
the same months.

A month is eligible for a rate only when its hours are reported, greater than
zero, and the month is closed. An open or unreported month is never treated as
zero: any window containing one is unavailable, with the months that block it
listed.

Event counts for a year come from one source: Incident & Near Miss
(``incidents``) from ``FIRST_INCIDENT_YEAR``, and the pre-platform workbook
counts (``performance_legacy``) before it. Closing an Incident & Near Miss
month confirms its counts are complete, so a count absent from it is zero.
Closing a legacy month does not: a legacy count is known only when a value is
stored (a typed value, or a zero proven by the source), and a window for a
measure is unavailable while any of its legacy months lacks that count.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from app.safety.rates import incidence_rate

FIRST_INCIDENT_YEAR = 2026
ROLLING_MONTHS = 12

INCIDENTS = "incidents"
PERFORMANCE_LEGACY = "performance_legacy"
CountSource = Literal["incidents", "performance_legacy"]

# (year, month)
Period = tuple[int, int]
# (section code, category code) within a metric set.
CategoryKey = tuple[str, str]


class Measure(StrEnum):
    TRIR = "trir"
    FIRST_AID = "first_aid"
    LOPC = "lopc"
    PROPERTY_EQUIPMENT_DAMAGE = "property_equipment_damage"


# Incident & Near Miss categories read for each numerator. TRIR adds recordable
# injuries and occupational illnesses; Lost Time Injury is a subset of
# recordable injuries and is not added again.
INCIDENT_CATEGORIES: dict[str, CategoryKey] = {
    "recordable_injury": ("incident_classification", "recordable_injury"),
    "occupational_illness": ("incident_classification", "occupational_illness"),
    "first_aid": ("incident_classification", "first_aid"),
    "lopc": ("lopc", "lopc"),
    "property_damage": ("incident_classification", "property_damage"),
    "equipment_damage_failure": ("incident_classification", "equipment_damage_failure"),
}

LEGACY_CATEGORIES: dict[str, CategoryKey] = {
    "recordable": ("recordable", "recordable"),
    "first_aid": ("first_aid", "first_aid"),
    "lopc": ("lopc", "lopc"),
    "property_equipment_damage": ("property_equipment_damage", "property_equipment_damage"),
}

IneligibleReason = Literal["not_reported", "open", "zero_hours"]
# Why a month blocks one measure's window: the month is ineligible, or it is an
# eligible legacy month without a stored count for that measure.
BlockReason = Literal["not_reported", "open", "zero_hours", "count_not_confirmed"]


def count_source(year: int) -> CountSource:
    return INCIDENTS if year >= FIRST_INCIDENT_YEAR else PERFORMANCE_LEGACY


@dataclass(frozen=True)
class MonthHours:
    total_hours: Decimal
    month_closed: bool


@dataclass(frozen=True)
class MonthCounts:
    """Event counts for one month, as rate numerators.

    ``None`` is an unconfirmed count. ``confirmed`` means every count is known:
    a closed Incident & Near Miss month, or a closed legacy month with all four
    counts stored.
    """

    source: CountSource
    confirmed: bool
    trir: int | None
    first_aid: int | None
    lopc: int | None
    property_equipment_damage: int | None
    # Incident & Near Miss only; the legacy workbook has no separate counts.
    recordable_injury: int | None
    occupational_illness: int | None
    property_damage: int | None
    equipment_damage_failure: int | None

    def numerator(self, measure: Measure) -> int | None:
        return {
            Measure.TRIR: self.trir,
            Measure.FIRST_AID: self.first_aid,
            Measure.LOPC: self.lopc,
            Measure.PROPERTY_EQUIPMENT_DAMAGE: self.property_equipment_damage,
        }[measure]


def _sum(*values: int | None) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def month_counts(source: CountSource, stored: Mapping[str, int], *, closed: bool) -> MonthCounts:
    """Numerators for one month from its stored values, keyed by the names in
    ``INCIDENT_CATEGORIES`` or ``LEGACY_CATEGORIES``."""
    if source == INCIDENTS:

        def value(name: str) -> int | None:
            found = stored.get(name)
            return 0 if found is None and closed else found

        injury, illness = value("recordable_injury"), value("occupational_illness")
        damage, equipment = value("property_damage"), value("equipment_damage_failure")
        return MonthCounts(
            source=source,
            confirmed=closed,
            trir=_sum(injury, illness),
            first_aid=value("first_aid"),
            lopc=value("lopc"),
            # Defined as property_damage + equipment_damage_failure. Monthly
            # aggregate counts cannot identify an event classified as both, so
            # such an event is counted twice; this is not a distinct-event count.
            property_equipment_damage=_sum(damage, equipment),
            recordable_injury=injury,
            occupational_illness=illness,
            property_damage=damage,
            equipment_damage_failure=equipment,
        )
    return MonthCounts(
        source=source,
        confirmed=closed and all(stored.get(name) is not None for name in LEGACY_CATEGORIES),
        trir=stored.get("recordable"),
        first_aid=stored.get("first_aid"),
        lopc=stored.get("lopc"),
        property_equipment_damage=stored.get("property_equipment_damage"),
        recordable_injury=None,
        occupational_illness=None,
        property_damage=None,
        equipment_damage_failure=None,
    )


def ineligible_reason(hours: MonthHours | None) -> IneligibleReason | None:
    if hours is None:
        return "not_reported"
    if not hours.month_closed:
        return "open"
    if hours.total_hours <= 0:
        return "zero_hours"
    return None


def shift(period: Period, months: int) -> Period:
    index = period[0] * 12 + (period[1] - 1) + months
    return index // 12, index % 12 + 1


def ytd_window(end: Period) -> list[Period]:
    return [(end[0], month) for month in range(1, end[1] + 1)]


def rolling_window(end: Period) -> list[Period]:
    return [shift(end, offset) for offset in range(-(ROLLING_MONTHS - 1), 1)]


def rate(events: int, hours: Decimal) -> float:
    exact = incidence_rate(events, hours)
    if exact is None:
        raise ValueError("a rate needs hours above zero")
    return float(exact)


@dataclass(frozen=True)
class IneligibleMonth:
    period: Period
    reason: BlockReason


@dataclass(frozen=True)
class WindowResult:
    measure: Measure
    start: Period
    end: Period
    ineligible: tuple[IneligibleMonth, ...]
    # Set only when every month in the window is eligible.
    events: int | None
    hours: Decimal | None
    rate: float | None
    # Supporting counts for Property & Equipment Damage when every month in the
    # window has them (Incident & Near Miss months only).
    property_damage: int | None = None
    equipment_damage_failure: int | None = None

    @property
    def available(self) -> bool:
        return self.rate is not None


def window_rate(
    measure: Measure,
    window: Sequence[Period],
    hours: Mapping[Period, MonthHours],
    counts: Mapping[Period, MonthCounts],
) -> WindowResult:
    ineligible = tuple(
        IneligibleMonth(period, reason)
        for period in window
        if (reason := _block_reason(measure, period, hours, counts)) is not None
    )
    start, end = window[0], window[-1]
    if ineligible:
        return WindowResult(measure, start, end, ineligible, None, None, None)

    month_counts_ = [counts[period] for period in window]
    events = sum(_required(c.numerator(measure)) for c in month_counts_)
    total_hours = sum((hours[period].total_hours for period in window), Decimal(0))
    property_damage = equipment = None
    if measure is Measure.PROPERTY_EQUIPMENT_DAMAGE and all(
        c.source == INCIDENTS for c in month_counts_
    ):
        property_damage = sum(_required(c.property_damage) for c in month_counts_)
        equipment = sum(_required(c.equipment_damage_failure) for c in month_counts_)
    return WindowResult(
        measure,
        start,
        end,
        (),
        events,
        total_hours,
        rate(events, total_hours),
        property_damage,
        equipment,
    )


def _block_reason(
    measure: Measure,
    period: Period,
    hours: Mapping[Period, MonthHours],
    counts: Mapping[Period, MonthCounts],
) -> BlockReason | None:
    if (reason := ineligible_reason(hours.get(period))) is not None:
        return reason
    if counts[period].numerator(measure) is None:
        return "count_not_confirmed"
    return None


def _required(value: int | None) -> int:
    # Windows with an unconfirmed count are rejected before summing.
    if value is None:
        raise ValueError("an eligible month has an unconfirmed count")
    return value


def latest_ytd_month(year: int, hours: Mapping[Period, MonthHours]) -> int | None:
    """The last month M for which January..M of ``year`` are all eligible."""
    latest = None
    for month in range(1, 13):
        if ineligible_reason(hours.get((year, month))) is not None:
            break
        latest = month
    return latest


@dataclass(frozen=True)
class AnnualResult:
    year: int
    basis: Literal["monthly", "annual_legacy"] | None
    # Set for a monthly year that is only complete through an earlier month.
    through_month: int | None
    events: int | None
    hours: Decimal | None
    rate: float | None

    @property
    def partial(self) -> bool:
        return self.basis == "monthly" and self.through_month != 12


@dataclass(frozen=True)
class AnnualLegacy:
    recordables: int
    total_hours: Decimal


def annual_trir(
    years: Sequence[int],
    hours: Mapping[Period, MonthHours],
    counts: Mapping[Period, MonthCounts],
    legacy: Mapping[int, AnnualLegacy],
) -> list[AnnualResult]:
    """TRIR per year: from monthly records for a year that has any, otherwise
    from the annual legacy row. A monthly year not yet complete is YTD through
    its latest eligible month."""
    results = []
    for year in years:
        if any(period[0] == year for period in hours):
            through = latest_ytd_month(year, hours)
            if through is None:
                results.append(AnnualResult(year, "monthly", None, None, None, None))
                continue
            window = window_rate(Measure.TRIR, ytd_window((year, through)), hours, counts)
            results.append(
                AnnualResult(year, "monthly", through, window.events, window.hours, window.rate)
            )
        elif (row := legacy.get(year)) is not None:
            results.append(
                AnnualResult(
                    year,
                    "annual_legacy",
                    None,
                    row.recordables,
                    row.total_hours,
                    rate(row.recordables, row.total_hours),
                )
            )
        else:
            results.append(AnnualResult(year, None, None, None, None, None))
    return results
