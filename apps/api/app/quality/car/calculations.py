"""Derived CAR values. Nothing here is stored.

- Days open: request date to the date closed, or to today while not closed.
- Past due: not closed and the due date is before today.
- Due soon: not closed and due within ``car_due_soon_days`` (today included).
- Awaiting effectiveness review: not closed, no effectiveness result yet and
  every corrective action complete (at least one).
- Cost impact: the sum of the entered cost lines; null when none is entered.

A report whose status is not recorded (older-form imports) counts as not closed.
"""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from app.quality.car.reference import COST_FIELDS, STEPS
from app.quality.cost.calculations import AGING_BUCKETS

StepState = Literal["not_started", "in_progress", "complete"]


class CarDates(Protocol):
    request_date: dt.date
    due_date: dt.date | None
    status: str | None
    date_closed: dt.date | None


class ActionState(Protocol):
    status: str | None
    target_date: dt.date | None


def is_closed(car: CarDates) -> bool:
    return car.status == "closed"


def days_open(car: CarDates, today: dt.date) -> int:
    end = car.date_closed if is_closed(car) and car.date_closed else today
    return max((end - car.request_date).days, 0)


def is_past_due(car: CarDates, today: dt.date) -> bool:
    return not is_closed(car) and car.due_date is not None and car.due_date < today


def is_due_soon(car: CarDates, today: dt.date, within_days: int) -> bool:
    return (
        not is_closed(car)
        and car.due_date is not None
        and today <= car.due_date <= today + dt.timedelta(days=within_days)
    )


def cost_total(car: object) -> Decimal | None:
    """The CAR's cost impact. Null (not 0) when no cost line is entered."""
    values = [getattr(car, field) for field, _ in COST_FIELDS]
    entered = [v for v in values if v is not None]
    return sum(entered, Decimal(0)) if entered else None


@dataclass(frozen=True)
class ActionProgress:
    total: int
    complete: int
    # Not complete (open, in progress, on hold or no status recorded).
    outstanding: int
    # Not complete and past their target date.
    overdue: int

    @property
    def all_complete(self) -> bool:
        return self.total > 0 and self.complete == self.total


def action_progress(actions: Sequence[ActionState], today: dt.date) -> ActionProgress:
    complete = sum(1 for a in actions if a.status == "complete")
    overdue = sum(
        1
        for a in actions
        if a.status != "complete" and a.target_date is not None and a.target_date < today
    )
    return ActionProgress(
        total=len(actions),
        complete=complete,
        outstanding=len(actions) - complete,
        overdue=overdue,
    )


def awaiting_effectiveness(car: object, progress: ActionProgress) -> bool:
    return (
        getattr(car, "status", None) != "closed"
        and getattr(car, "effectiveness_result", None) is None
        and progress.all_complete
    )


@dataclass(frozen=True)
class AgingBucket:
    label: str
    min_days: int
    max_days: int | None
    count: int


def aging(cars: Iterable[CarDates], today: dt.date) -> list[AgingBucket]:
    """Reports not closed, by days open (the Quality Cost aging bands)."""
    ages = [days_open(c, today) for c in cars if not is_closed(c)]
    return [
        AgingBucket(
            label=label,
            min_days=low,
            max_days=high,
            count=sum(1 for d in ages if d >= low and (high is None or d <= high)),
        )
        for label, low, high in AGING_BUCKETS
    ]


# What each step of the form asks for. A step is complete when every item is
# recorded, in progress when some are.
_STEP_FIELDS: dict[str, tuple[str, ...]] = {
    "identify": (
        "requested_by",
        "assigned_to",
        "due_date",
        "source_code",
        "department_code",
        "nonconformity_description",
    ),
    "contain": (
        "immediate_actions",
        "containment_owner",
        "containment_completed_on",
        "disposition_codes",
        "safety_hazard",
        "environmental_hazard",
        "customer_impact",
    ),
    "investigate": (
        "incident_type",
        "root_cause_code",
        "investigation_summary",
        "true_root_cause",
    ),
    "evaluate": ("similar_nonconformities", "similar_issue_found", "additional_action_required"),
    "verify": (
        "success_criteria",
        "effectiveness_evidence",
        "reviewer",
        "review_date",
        "effectiveness_result",
    ),
    "cost": tuple(field for field, _ in COST_FIELDS),
}


def _recorded(value: object) -> bool:
    return value is not None and value != [] and value != ()


def _state(done: int, total: int) -> StepState:
    if total and done == total:
        return "complete"
    return "in_progress" if done else "not_started"


def step_states(
    car: object, progress: ActionProgress, approvals: int
) -> list[tuple[str, str, StepState]]:
    """(code, label, state) for each step of the form, in order."""
    states: dict[str, StepState] = {}
    for code, fields in _STEP_FIELDS.items():
        states[code] = _state(sum(_recorded(getattr(car, f)) for f in fields), len(fields))
    states["correct"] = (
        "complete" if progress.all_complete else "in_progress" if progress.total else "not_started"
    )
    if is_closed(car):  # type: ignore[arg-type]
        states["close"] = "complete"
    else:
        started = approvals or getattr(car, "closure_approved_by", None)
        states["close"] = "in_progress" if started else "not_started"
    return [(code, label, states[code]) for code, label in STEPS]
