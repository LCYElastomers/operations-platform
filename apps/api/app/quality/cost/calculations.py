"""Quality Cost record calculations: the one place figures are derived.

Every view (Register, COPQ, COQ Matrix) uses these, so a record contributes
the same amount everywhere. Decimal throughout; rounding is for display only.

- A record's total is the sum of its entered cost components; null when none
  is entered (unknown cost), distinct from an entered 0.
- Confirmed cost is the total of records whose financial status is Confirmed
  or Closed. Potential exposure is the total of Potential and Validating
  records. The two are reported separately and never silently combined;
  total exposure is their explicit sum.
- Recovered and avoided costs count from confirmed records only, like the
  cost they offset. Net quality cost = confirmed cost − recovered cost.
  Avoided cost is reported on its own and never subtracted.
- Good COQ = Prevention + Appraisal; Poor COQ (COPQ) = Internal + External
  Failure; Total COQ = Good + Poor, null unless both are recorded; Poor % =
  Poor ÷ Total (null when the total is null or not positive).
- Days open runs from the record date to the date closed, or to today for a
  record that is not closed. It is derived, never stored.
"""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.quality.cost.classification import (
    COMPONENT_FIELDS,
    CONFIRMED_FINANCIAL,
    POTENTIAL_FINANCIAL,
    is_poor,
)

AGING_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0–30 days", 0, 30),
    ("31–60 days", 31, 60),
    ("61–90 days", 61, 90),
    ("Over 90 days", 91, None),
)


class CostedRecord(Protocol):
    record_date: dt.date
    coq_class: str
    financial_status: str
    status: str
    due_date: dt.date | None
    date_closed: dt.date | None
    recovered_cost: Decimal | None
    avoided_cost: Decimal | None


def total(values: Iterable[Decimal | None]) -> Decimal | None:
    """The sum of the entered values; null when none is entered."""
    entered = [v for v in values if v is not None]
    return sum(entered, Decimal(0)) if entered else None


def ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def record_total(record: object) -> Decimal | None:
    """Estimated total cost: the sum of the entered cost components."""
    return total(getattr(record, field) for field in COMPONENT_FIELDS)


def is_confirmed(record: CostedRecord) -> bool:
    return record.financial_status in CONFIRMED_FINANCIAL


def is_potential(record: CostedRecord) -> bool:
    return record.financial_status in POTENTIAL_FINANCIAL


def is_open(record: CostedRecord) -> bool:
    return record.status != "closed"


def record_net(record: CostedRecord) -> Decimal | None:
    """The record's total less what was recovered; null when no cost is entered."""
    cost = record_total(record)
    if cost is None:
        return None
    return cost - (record.recovered_cost or Decimal(0))


def days_open(record: CostedRecord, today: dt.date) -> int:
    end = record.date_closed or today
    return max((end - record.record_date).days, 0)


def is_overdue(record: CostedRecord, today: dt.date) -> bool:
    return record.due_date is not None and is_open(record) and record.due_date < today


@dataclass(frozen=True)
class CostTotals:
    """Totals of a set of records. Null is no cost entered, never 0."""

    count: int
    confirmed_count: int
    potential_count: int
    # Records with no cost component entered.
    no_cost_count: int
    confirmed: Decimal | None
    potential: Decimal | None
    total_exposure: Decimal | None
    recovered: Decimal | None
    avoided: Decimal | None
    net: Decimal | None


def totals(records: Sequence[CostedRecord]) -> CostTotals:
    confirmed = [r for r in records if is_confirmed(r)]
    potential = [r for r in records if is_potential(r)]
    confirmed_cost = total(record_total(r) for r in confirmed)
    potential_cost = total(record_total(r) for r in potential)
    recovered = total(r.recovered_cost for r in confirmed)
    return CostTotals(
        count=len(records),
        confirmed_count=len(confirmed),
        potential_count=len(potential),
        no_cost_count=sum(1 for r in records if record_total(r) is None),
        confirmed=confirmed_cost,
        potential=potential_cost,
        total_exposure=total((confirmed_cost, potential_cost)),
        recovered=recovered,
        avoided=total(r.avoided_cost for r in confirmed),
        net=None if confirmed_cost is None else confirmed_cost - (recovered or Decimal(0)),
    )


def poor_records(records: Iterable[CostedRecord]) -> list[CostedRecord]:
    """Internal and external failure records: the records behind COPQ."""
    return [r for r in records if is_poor(r.coq_class)]


@dataclass(frozen=True)
class MatrixFigures:
    good: Decimal | None
    poor: Decimal | None
    total: Decimal | None
    poor_pct: Decimal | None


def matrix(by_class: dict[str, Decimal | None]) -> MatrixFigures:
    """Good, poor and total COQ from per-class amounts.

    Total COQ and poor % need both good and poor cost: with no good cost
    recorded, the total is unknown rather than equal to the poor cost.
    """
    good = total((by_class.get("prevention"), by_class.get("appraisal")))
    poor = total((by_class.get("internal_failure"), by_class.get("external_failure")))
    overall = None if good is None or poor is None else good + poor
    return MatrixFigures(good=good, poor=poor, total=overall, poor_pct=ratio(poor, overall))


@dataclass(frozen=True)
class AgingBucket:
    label: str
    min_days: int
    max_days: int | None
    count: int
    exposure: Decimal | None


def aging(records: Sequence[CostedRecord], today: dt.date) -> list[AgingBucket]:
    """Open records by days open, with their cost (confirmed and potential)."""
    open_records = [r for r in records if is_open(r)]
    buckets = []
    for label, low, high in AGING_BUCKETS:
        inside = [
            r
            for r in open_records
            if days_open(r, today) >= low and (high is None or days_open(r, today) <= high)
        ]
        buckets.append(
            AgingBucket(
                label=label,
                min_days=low,
                max_days=high,
                count=len(inside),
                exposure=total(record_total(r) for r in inside),
            )
        )
    return buckets
