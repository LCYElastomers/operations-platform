"""CAR dashboard figures, calculated from the same reports the register lists."""

import datetime as dt
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal

from app.quality.car import calculations
from app.quality.car.reference import (
    CAR_STATUSES,
    EFFECTIVENESS_RESULTS,
    ROOT_CAUSE_CATEGORIES,
    SOURCES,
    STATUS_NOT_RECORDED,
    department_label,
)
from app.quality.car.repository import CarRow
from app.quality.car.schemas import (
    AgingBucketOut,
    CarCostOut,
    CarDashboardResponse,
    CarKpisOut,
    CostByOut,
    CountOut,
    RepeatCarOut,
    TrendMonthOut,
)

TREND_MONTHS = 12


def _counts(
    values: Sequence[str | None], labels: dict[str, str] | None, label_of=None
) -> list[CountOut]:
    """Counts by code, most frequent first; "Not recorded" last."""
    counter = Counter(values)
    recorded = sorted(
        ((code, n) for code, n in counter.items() if code is not None),
        key=lambda item: (-item[1], item[0]),
    )
    out = [
        CountOut(
            code=code,
            label=label_of(code) if label_of else (labels or {}).get(code, code),
            count=n,
        )
        for code, n in recorded
    ]
    if counter.get(None):
        out.append(CountOut(code=None, label=STATUS_NOT_RECORDED, count=counter[None]))
    return out


def _fixed_counts(values: Sequence[str | None], labels: dict[str, str]) -> list[CountOut]:
    """Counts for every listed code in list order (zeros included), then not recorded."""
    counter = Counter(values)
    out = [
        CountOut(code=code, label=label, count=counter.get(code, 0))
        for code, label in labels.items()
    ]
    out.append(CountOut(code=None, label=STATUS_NOT_RECORDED, count=counter.get(None, 0)))
    return out


def _trend(rows: Sequence[CarRow], today: dt.date) -> list[TrendMonthOut]:
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(TREND_MONTHS):
        months.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    opened = Counter((r.car.request_date.year, r.car.request_date.month) for r in rows)
    closed = Counter(
        (r.car.date_closed.year, r.car.date_closed.month)
        for r in rows
        if r.car.status == "closed" and r.car.date_closed is not None
    )
    return [
        TrendMonthOut(year=y, month=m, opened=opened.get((y, m), 0), closed=closed.get((y, m), 0))
        for y, m in reversed(months)
    ]


def summary(rows: Sequence[CarRow], *, today: dt.date, due_soon_days: int) -> CarDashboardResponse:
    cars = [r.car for r in rows]
    progress = {r.car.id: calculations.action_progress(r.actions, today) for r in rows}
    not_closed = [c for c in cars if not calculations.is_closed(c)]

    kpis = CarKpisOut(
        total=len(cars),
        open=len(not_closed),
        past_due=sum(calculations.is_past_due(c, today) for c in cars),
        due_soon=sum(calculations.is_due_soon(c, today, due_soon_days) for c in cars),
        awaiting_effectiveness=sum(
            calculations.awaiting_effectiveness(c, progress[c.id]) for c in cars
        ),
        closed_ytd=sum(
            1
            for c in cars
            if calculations.is_closed(c)
            and c.date_closed is not None
            and c.date_closed.year == today.year
        ),
        status_not_recorded=sum(1 for c in cars if c.status is None),
        actions_overdue=sum(p.overdue for p in progress.values()),
    )

    totals = [(c, calculations.cost_total(c)) for c in cars]
    with_cost = [(c, t) for c, t in totals if t is not None]
    by_department: dict[str | None, list[Decimal]] = {}
    for c, t in with_cost:
        by_department.setdefault(c.department_code, []).append(t)  # type: ignore[arg-type]
    cost = CarCostOut(
        total=sum((t for _, t in with_cost), Decimal(0)) if with_cost else None,  # type: ignore[misc]
        with_cost=len(with_cost),
        without_cost=len(cars) - len(with_cost),
        linked_to_quality_cost=sum(1 for c in cars if c.quality_cost_record_id is not None),
        by_department=sorted(
            (
                CostByOut(
                    code=code,
                    label=department_label(code) or STATUS_NOT_RECORDED,
                    total=sum(values, Decimal(0)),
                    count=len(values),
                )
                for code, values in by_department.items()
            ),
            key=lambda item: -item.total,
        ),
    )

    return CarDashboardResponse(
        today=today,
        year=today.year,
        due_soon_days=due_soon_days,
        kpis=kpis,
        by_status=_fixed_counts([c.status for c in cars], CAR_STATUSES),
        by_department=_counts([c.department_code for c in cars], None, department_label),
        by_source=_counts([c.source_code for c in cars], SOURCES),
        by_root_cause=_counts([c.root_cause_code for c in cars], ROOT_CAUSE_CATEGORIES),
        effectiveness=_fixed_counts([c.effectiveness_result for c in cars], EFFECTIVENESS_RESULTS),
        repeat=[
            CountOut(
                code="yes",
                label="Repeat",
                count=sum(1 for c in cars if c.previous_occurrence is True),
            ),
            CountOut(
                code="no",
                label="Not a repeat",
                count=sum(1 for c in cars if c.previous_occurrence is False),
            ),
            CountOut(
                code=None,
                label=STATUS_NOT_RECORDED,
                count=sum(1 for c in cars if c.previous_occurrence is None),
            ),
        ],
        repeat_cars=[
            RepeatCarOut(
                id=c.id, car_number=c.car_number, subject=c.subject, previous_car=c.previous_car
            )
            for c in cars
            if c.previous_occurrence is True
        ],
        trend=_trend(rows, today),
        aging=[
            AgingBucketOut(label=b.label, min_days=b.min_days, max_days=b.max_days, count=b.count)
            for b in calculations.aging(cars, today)
        ],
        cost=cost,
    )
