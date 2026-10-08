"""Safety Observation rules: audited record changes and counts derived from records.

Every count (total, safe/unsafe, act/condition, per category, per month) is
computed from the same observation rows, so no figure can disagree with
another. Counts are true counts of records: a started month without records
counts 0. Months that have not started yet are null, not 0. "Today" is the
Baytown site's calendar date (``app.safety.site_calendar``).
"""

import calendar
import datetime as dt
import logging
import uuid
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from app.audit.recorder import AuditChange
from app.safety.observations.repository import (
    CategoryDefinition,
    CountRow,
    ObservationFilter,
    ObservationRecord,
    ObservationRepository,
    ObservationValues,
)
from app.safety.observations.schemas import (
    CategoryCount,
    DashboardCategory,
    DashboardMonth,
    ObservationCounts,
    ObservationDashboardResponse,
    ObservationInput,
    ObservationOut,
    ObservationSummaryResponse,
    ObservationUpdate,
)
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

AUDIT_ENTITY_TYPE = "safety.observation"
MONTHS = range(1, 13)


class UnknownCategoryError(ValueError):
    """The category does not exist or is no longer offered for new entries."""

    def __init__(self, category_id: int) -> None:
        super().__init__("unknown category")
        self.category_id = category_id


class ObservedOnInFutureError(ValueError):
    def __init__(self, today: dt.date) -> None:
        super().__init__("observed date is in the future")
        self.today = today


class ObservationNotFoundError(LookupError):
    pass


class EditConflictError(RuntimeError):
    """The observation changed since the client loaded it. Nothing was written."""

    def __init__(self, current: ObservationRecord) -> None:
        super().__init__("edit conflict")
        self.current = current


def entity_key(observation_id: int) -> str:
    return f"observations/{observation_id}"


def to_out(record: ObservationRecord) -> ObservationOut:
    v = record.values
    return ObservationOut(
        id=record.id,
        observed_on=v.observed_on,
        outcome=v.outcome,  # type: ignore[arg-type]
        kind=v.kind,  # type: ignore[arg-type]
        category_id=v.category_id,
        category_code=record.category_code,
        category_name=record.category_name,
        area_location=v.area_location,
        description=v.description,
        corrective_action=v.corrective_action,
        created_at=record.created_at,
        created_by=record.created_by,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
    )


def _values(data: ObservationInput) -> ObservationValues:
    return ObservationValues(
        observed_on=data.observed_on,
        outcome=data.outcome,
        kind=data.kind,
        category_id=data.category_id,
        area_location=data.area_location,
        description=data.description,
        corrective_action=data.corrective_action,
    )


def _snapshot(values: ObservationValues, category_code: str) -> dict[str, Any]:
    return {
        "observed_on": values.observed_on.isoformat(),
        "outcome": values.outcome,
        "kind": values.kind,
        "category": category_code,
        "area_location": values.area_location,
        "description": values.description,
        "corrective_action": values.corrective_action,
    }


def _check_observed_on(observed_on: dt.date, now: dt.datetime) -> None:
    today = site_today(now)
    if observed_on > today:
        raise ObservedOnInFutureError(today)


def _active_category(repository: ObservationRepository, category_id: int) -> CategoryDefinition:
    category = next((c for c in repository.categories() if c.id == category_id), None)
    if category is None or not category.active:
        raise UnknownCategoryError(category_id)
    return category


def active_categories(repository: ObservationRepository) -> list[CategoryDefinition]:
    return [category for category in repository.categories() if category.active]


def _audit(
    repository: ObservationRepository,
    *,
    action: Literal["create", "update", "delete"],
    observation_id: int,
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
    actor_id: str,
    now: dt.datetime,
) -> uuid.UUID:
    change_set_id = uuid.uuid4()
    repository.record_audit(
        actor_id=actor_id,
        change_set_id=change_set_id,
        at=now,
        changes=[
            AuditChange(
                action=action,
                entity_type=AUDIT_ENTITY_TYPE,
                entity_key=entity_key(observation_id),
                old_value=old,
                new_value=new,
            )
        ],
    )
    return change_set_id


def _log_saved(action: str, observation_id: int, actor_id: str, change_set_id: uuid.UUID) -> None:
    # Identifiers only: free-text fields are never logged.
    logger.info(
        "event=safety_observation_saved action=%s observation_id=%s user=%s change_set=%s",
        action,
        observation_id,
        actor_id,
        change_set_id,
    )


def _reload(repository: ObservationRepository, observation_id: int) -> ObservationRecord:
    record = repository.get(observation_id)
    assert record is not None  # noqa: S101 - just written in a committed transaction
    return record


def create_observation(
    repository: ObservationRepository,
    data: ObservationInput,
    *,
    actor_id: str,
    now: dt.datetime,
) -> ObservationRecord:
    values = _values(data)
    _check_observed_on(values.observed_on, now)
    category = _active_category(repository, values.category_id)

    observation_id = repository.insert(values, actor_id=actor_id, at=now)
    change_set_id = _audit(
        repository,
        action="create",
        observation_id=observation_id,
        old=None,
        new=_snapshot(values, category.code),
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("create", observation_id, actor_id, change_set_id)
    return _reload(repository, observation_id)


def update_observation(
    repository: ObservationRepository,
    observation_id: int,
    data: ObservationUpdate,
    *,
    actor_id: str,
    now: dt.datetime,
) -> ObservationRecord:
    """Replace an observation's fields. An unchanged observation is not written or audited."""
    values = _values(data)
    _check_observed_on(values.observed_on, now)

    current = repository.get(observation_id, for_update=True)
    if current is None:
        repository.rollback()
        raise ObservationNotFoundError(observation_id)
    if current.updated_at != data.expected_updated_at:
        repository.rollback()
        raise EditConflictError(current)
    if values == current.values:
        repository.rollback()
        return current

    # An observation may keep a category that was retired after it was entered.
    if values.category_id == current.values.category_id:
        category_code = current.category_code
    else:
        try:
            category_code = _active_category(repository, values.category_id).code
        except UnknownCategoryError:
            repository.rollback()
            raise

    repository.update(observation_id, values, actor_id=actor_id, at=now)
    change_set_id = _audit(
        repository,
        action="update",
        observation_id=observation_id,
        old=_snapshot(current.values, current.category_code),
        new=_snapshot(values, category_code),
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("update", observation_id, actor_id, change_set_id)
    return _reload(repository, observation_id)


def delete_observation(
    repository: ObservationRepository,
    observation_id: int,
    *,
    actor_id: str,
    now: dt.datetime,
) -> None:
    """Delete an observation. Its last values remain in core.audit_events."""
    current = repository.get(observation_id, for_update=True)
    if current is None:
        repository.rollback()
        raise ObservationNotFoundError(observation_id)
    repository.delete(observation_id)
    change_set_id = _audit(
        repository,
        action="delete",
        observation_id=observation_id,
        old=_snapshot(current.values, current.category_code),
        new=None,
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("delete", observation_id, actor_id, change_set_id)


# Counts --------------------------------------------------------------------------


def period(year: int, month: int | None = None) -> ObservationFilter:
    """Filter for a calendar year, or one month of it."""
    if month is None:
        return ObservationFilter(
            observed_from=dt.date(year, 1, 1), observed_to=dt.date(year, 12, 31)
        )
    last_day = calendar.monthrange(year, month)[1]
    return ObservationFilter(
        observed_from=dt.date(year, month, 1), observed_to=dt.date(year, month, last_day)
    )


def count_summary(rows: Iterable[CountRow]) -> ObservationCounts:
    tally = {(o, k): 0 for o in ("safe", "unsafe") for k in ("act", "condition")}
    for row in rows:
        tally[(row.outcome, row.kind)] += row.count
    safe = tally[("safe", "act")] + tally[("safe", "condition")]
    unsafe = tally[("unsafe", "act")] + tally[("unsafe", "condition")]
    return ObservationCounts(
        total=safe + unsafe,
        safe=safe,
        unsafe=unsafe,
        safe_act=tally[("safe", "act")],
        safe_condition=tally[("safe", "condition")],
        unsafe_act=tally[("unsafe", "act")],
        unsafe_condition=tally[("unsafe", "condition")],
    )


def _counted_categories(
    categories: Sequence[CategoryDefinition], rows: Sequence[CountRow]
) -> list[CategoryDefinition]:
    """Active categories, plus retired ones that still have observations in the period."""
    used = {row.category_id for row in rows}
    return [c for c in categories if c.active or c.id in used]


def _category_count(category: CategoryDefinition, rows: Sequence[CountRow]) -> CategoryCount:
    counts = count_summary(row for row in rows if row.category_id == category.id)
    return CategoryCount(
        category_id=category.id,
        code=category.code,
        name=category.name,
        total=counts.total,
        safe=counts.safe,
        unsafe=counts.unsafe,
    )


def summarize(
    repository: ObservationRepository, *, year: int, month: int | None
) -> ObservationSummaryResponse:
    rows = repository.counts(period(year, month))
    return ObservationSummaryResponse(
        year=year,
        month=month,
        counts=count_summary(rows),
        categories=[
            _category_count(category, rows)
            for category in _counted_categories(repository.categories(), rows)
        ],
    )


def started_months(year: int, today: dt.date) -> int:
    """How many months of ``year`` have started by ``today`` (0-12)."""
    if year < today.year:
        return 12
    if year > today.year:
        return 0
    return today.month


def build_dashboard(
    *,
    year: int,
    today: dt.date,
    categories: Sequence[CategoryDefinition],
    rows: Sequence[CountRow],
    years_with_data: Sequence[int],
) -> ObservationDashboardResponse:
    through = started_months(year, today)
    recorded_months = {row.month for row in rows}

    def shown(month: int) -> bool:
        return month <= through or month in recorded_months

    def in_month(month: int) -> list[CountRow]:
        return [row for row in rows if row.month == month]

    counts = count_summary(rows)
    dashboard_categories = []
    for category in _counted_categories(categories, rows):
        own = [row for row in rows if row.category_id == category.id]
        base = _category_count(category, own)
        dashboard_categories.append(
            DashboardCategory(
                **base.model_dump(),
                monthly=[
                    sum(row.count for row in own if row.month == month) if shown(month) else None
                    for month in MONTHS
                ],
            )
        )
    return ObservationDashboardResponse(
        year=year,
        through_month=through,
        counts=counts,
        unsafe_share=counts.unsafe / counts.total if counts.total else None,
        months=[
            DashboardMonth(
                month=month, counts=count_summary(in_month(month)) if shown(month) else None
            )
            for month in MONTHS
        ],
        categories=dashboard_categories,
        years_with_data=list(years_with_data),
    )


def dashboard(
    repository: ObservationRepository, *, year: int, today: dt.date
) -> ObservationDashboardResponse:
    return build_dashboard(
        year=year,
        today=today,
        categories=repository.categories(),
        rows=repository.counts(period(year)),
        years_with_data=repository.years_with_observations(),
    )
