"""Supervisor Safety Contact rules: audited changes and counts derived from records.

Every figure (contacts per month, per supervisor, year to date, participation)
is counted from the same contact rows. A started month without contacts counts
0; months that have not started yet are null, not 0.

Participation for a month is the number of eligible supervisors with at least
one contact in the month, out of the supervisors eligible for that month. A
supervisor is eligible for a month when they are marked participation
eligible and their effective period overlaps the month. No target is applied:
the figures describe the program, they do not rate individuals.

"Today" is the Baytown site's calendar date (``app.safety.site_calendar``).
"""

import calendar
import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from app.audit.recorder import AuditChange
from app.safety.contacts.repository import (
    ContactFilter,
    ContactRecord,
    ContactRepository,
    ContactValues,
    CountRow,
    DuplicateDisplayNameError,
    SupervisorRecord,
    SupervisorReferencedError,
    SupervisorValues,
)
from app.safety.contacts.schemas import (
    ContactCreate,
    ContactDashboardResponse,
    ContactOut,
    ContactSummaryResponse,
    ContactUpdate,
    DashboardMonth,
    DashboardSupervisor,
    Participation,
    SupervisorCount,
    SupervisorInput,
    SupervisorOut,
    SupervisorUpdate,
)
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

CONTACT_ENTITY_TYPE = "safety.contact"
SUPERVISOR_ENTITY_TYPE = "safety.contact_supervisor"
MONTHS = range(1, 13)


class ContactRuleError(ValueError):
    """The request breaks a program rule. Nothing was written."""

    def __init__(self, error: str, message: str, **details: Any) -> None:
        # details keys are the API's camelCase names; they are returned with the error.
        super().__init__(message)
        self.error = error
        self.message = message
        self.details = details


class SupervisorNotFoundError(LookupError):
    pass


class ContactNotFoundError(LookupError):
    pass


class SupervisorHasContactsError(RuntimeError):
    """A supervisor with contacts cannot be deleted; set them inactive instead."""


class RequestReusedError(RuntimeError):
    """The request id was already used for a different contact."""

    def __init__(self, existing: ContactRecord) -> None:
        super().__init__("request id reused")
        self.existing = existing


class EditConflictError(RuntimeError):
    """The record changed since the client loaded it. Nothing was written."""

    def __init__(self, current: ContactRecord | SupervisorRecord) -> None:
        super().__init__("edit conflict")
        self.current = current


def contact_key(contact_id: int) -> str:
    return f"contacts/{contact_id}"


def supervisor_key(supervisor_id: int) -> str:
    return f"contact-supervisors/{supervisor_id}"


def contact_out(record: ContactRecord) -> ContactOut:
    return ContactOut(
        id=record.id,
        contact_date=record.values.contact_date,
        supervisor_id=record.values.supervisor_id,
        supervisor_name=record.supervisor_name,
        created_at=record.created_at,
        created_by=record.created_by,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
    )


def supervisor_out(record: SupervisorRecord) -> SupervisorOut:
    v = record.values
    return SupervisorOut(
        id=record.id,
        display_name=v.display_name,
        active=v.active,
        participation_eligible=v.participation_eligible,
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        has_contacts=record.has_contacts,
        created_at=record.created_at,
        created_by=record.created_by,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
    )


def _contact_snapshot(values: ContactValues) -> dict[str, Any]:
    return {"contact_date": values.contact_date.isoformat(), "supervisor_id": values.supervisor_id}


def _supervisor_snapshot(values: SupervisorValues) -> dict[str, Any]:
    return {
        "display_name": values.display_name,
        "active": values.active,
        "participation_eligible": values.participation_eligible,
        "effective_from": values.effective_from.isoformat(),
        "effective_to": values.effective_to.isoformat() if values.effective_to else None,
    }


def _audit(
    repository: ContactRepository,
    *,
    action: Literal["create", "update", "delete"],
    entity_type: str,
    entity_key: str,
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
                entity_type=entity_type,
                entity_key=entity_key,
                old_value=old,
                new_value=new,
            )
        ],
    )
    return change_set_id


def _log_saved(
    event: str, action: str, record_id: int, actor_id: str, change_set_id: uuid.UUID
) -> None:
    # Identifiers only: supervisor names are never logged.
    logger.info(
        "event=%s action=%s id=%s user=%s change_set=%s",
        event,
        action,
        record_id,
        actor_id,
        change_set_id,
    )


def _in_effect(values: SupervisorValues, start: dt.date, end: dt.date) -> bool:
    """Whether the supervisor's effective period overlaps [start, end]."""
    return values.effective_from <= end and (
        values.effective_to is None or values.effective_to >= start
    )


# Supervisors ---------------------------------------------------------------------


def _supervisor_values(data: SupervisorInput) -> SupervisorValues:
    return SupervisorValues(
        display_name=data.display_name,
        active=data.active,
        participation_eligible=data.participation_eligible,
        effective_from=data.effective_from,
        effective_to=data.effective_to,
    )


def _check_supervisor(
    repository: ContactRepository, values: SupervisorValues, supervisor_id: int | None
) -> None:
    if values.effective_to is not None and values.effective_to < values.effective_from:
        raise ContactRuleError(
            "effective_period_invalid", "The end date cannot be before the start date."
        )
    if not values.active and values.effective_to is None:
        raise ContactRuleError(
            "inactive_requires_end_date",
            "An inactive supervisor needs an end date, so later months do not count them.",
        )
    name = values.display_name.lower()
    if any(
        s.values.display_name.lower() == name and s.id != supervisor_id
        for s in repository.supervisors()
    ):
        raise ContactRuleError(
            "duplicate_display_name", "Another supervisor already has this name."
        )


def _duplicate_name() -> ContactRuleError:
    return ContactRuleError("duplicate_display_name", "Another supervisor already has this name.")


def create_supervisor(
    repository: ContactRepository, data: SupervisorInput, *, actor_id: str, now: dt.datetime
) -> SupervisorRecord:
    values = _supervisor_values(data)
    _check_supervisor(repository, values, None)
    try:
        supervisor_id = repository.insert_supervisor(values, actor_id=actor_id, at=now)
    except DuplicateDisplayNameError:
        repository.rollback()
        raise _duplicate_name() from None
    change_set_id = _audit(
        repository,
        action="create",
        entity_type=SUPERVISOR_ENTITY_TYPE,
        entity_key=supervisor_key(supervisor_id),
        old=None,
        new=_supervisor_snapshot(values),
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("safety_contact_supervisor_saved", "create", supervisor_id, actor_id, change_set_id)
    return _reload_supervisor(repository, supervisor_id)


def update_supervisor(
    repository: ContactRepository,
    supervisor_id: int,
    data: SupervisorUpdate,
    *,
    actor_id: str,
    now: dt.datetime,
) -> SupervisorRecord:
    """Replace a supervisor's fields. An unchanged supervisor is not written or audited.

    The effective period cannot be narrowed to exclude contacts already credited.
    """
    values = _supervisor_values(data)
    current = repository.get_supervisor(supervisor_id, lock="update")
    if current is None:
        repository.rollback()
        raise SupervisorNotFoundError(supervisor_id)
    if current.updated_at != data.expected_updated_at:
        repository.rollback()
        raise EditConflictError(current)
    if values == current.values:
        repository.rollback()
        return current
    try:
        _check_supervisor(repository, values, supervisor_id)
        outside = repository.contacts_outside(
            supervisor_id, values.effective_from, values.effective_to
        )
        if outside:
            raise ContactRuleError(
                "contacts_outside_effective_period",
                "Contacts already recorded for this supervisor fall outside these dates.",
                contacts=outside,
            )
        repository.update_supervisor(supervisor_id, values, actor_id=actor_id, at=now)
    except DuplicateDisplayNameError:
        repository.rollback()
        raise _duplicate_name() from None
    except ContactRuleError:
        repository.rollback()
        raise
    change_set_id = _audit(
        repository,
        action="update",
        entity_type=SUPERVISOR_ENTITY_TYPE,
        entity_key=supervisor_key(supervisor_id),
        old=_supervisor_snapshot(current.values),
        new=_supervisor_snapshot(values),
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("safety_contact_supervisor_saved", "update", supervisor_id, actor_id, change_set_id)
    return _reload_supervisor(repository, supervisor_id)


def delete_supervisor(
    repository: ContactRepository, supervisor_id: int, *, actor_id: str, now: dt.datetime
) -> None:
    """Delete a supervisor added by mistake. One with contacts is kept (set inactive instead)."""
    current = repository.get_supervisor(supervisor_id, lock="update")
    if current is None:
        repository.rollback()
        raise SupervisorNotFoundError(supervisor_id)
    if current.has_contacts:
        repository.rollback()
        raise SupervisorHasContactsError(supervisor_id)
    try:
        repository.delete_supervisor(supervisor_id)
    except SupervisorReferencedError:
        repository.rollback()
        raise SupervisorHasContactsError(supervisor_id) from None
    change_set_id = _audit(
        repository,
        action="delete",
        entity_type=SUPERVISOR_ENTITY_TYPE,
        entity_key=supervisor_key(supervisor_id),
        old=_supervisor_snapshot(current.values),
        new=None,
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("safety_contact_supervisor_saved", "delete", supervisor_id, actor_id, change_set_id)


def _reload_supervisor(repository: ContactRepository, supervisor_id: int) -> SupervisorRecord:
    record = repository.get_supervisor(supervisor_id)
    assert record is not None  # noqa: S101 - just written in a committed transaction
    return record


# Contacts ------------------------------------------------------------------------


def _check_contact_date(contact_date: dt.date, now: dt.datetime) -> None:
    today = site_today(now)
    if contact_date > today:
        raise ContactRuleError(
            "contact_date_in_future",
            "The contact date cannot be in the future.",
            today=today.isoformat(),
        )


def _creditable_supervisor(
    repository: ContactRepository, values: ContactValues, *, allow_inactive: bool
) -> SupervisorRecord:
    """The supervisor, locked against changes, if the contact can be credited to them."""
    supervisor = repository.get_supervisor(values.supervisor_id, lock="share")
    if supervisor is None:
        raise ContactRuleError(
            "unknown_supervisor",
            "The supervisor does not exist.",
            supervisorId=values.supervisor_id,
        )
    if not supervisor.values.active and not allow_inactive:
        raise ContactRuleError(
            "supervisor_inactive",
            "The supervisor is inactive and cannot be credited with new contacts.",
            supervisorId=values.supervisor_id,
        )
    if not _in_effect(supervisor.values, values.contact_date, values.contact_date):
        raise ContactRuleError(
            "outside_effective_period",
            "The contact date is outside the supervisor's effective dates.",
            supervisorId=values.supervisor_id,
        )
    return supervisor


def _replayed(existing: ContactRecord, values: ContactValues) -> ContactRecord:
    if existing.values != values:
        raise RequestReusedError(existing)
    return existing


def create_contact(
    repository: ContactRepository, data: ContactCreate, *, actor_id: str, now: dt.datetime
) -> tuple[ContactRecord, bool]:
    """Record one contact. Returns the contact and whether it was newly created.

    Resubmitting a ``request_id`` returns the contact already recorded for it.
    """
    values = ContactValues(contact_date=data.contact_date, supervisor_id=data.supervisor_id)
    _check_contact_date(values.contact_date, now)
    if data.request_id is not None:
        existing = repository.get_by_request(data.request_id)
        if existing is not None:
            repository.rollback()
            return _replayed(existing, values), False

    try:
        _creditable_supervisor(repository, values, allow_inactive=False)
    except ContactRuleError:
        repository.rollback()
        raise
    contact_id = repository.insert(values, request_id=data.request_id, actor_id=actor_id, at=now)
    if contact_id is None:
        # The same request committed concurrently.
        repository.rollback()
        assert data.request_id is not None  # noqa: S101 - only a request id can conflict
        existing = repository.get_by_request(data.request_id)
        assert existing is not None  # noqa: S101 - the conflicting row is committed
        return _replayed(existing, values), False

    change_set_id = _audit(
        repository,
        action="create",
        entity_type=CONTACT_ENTITY_TYPE,
        entity_key=contact_key(contact_id),
        old=None,
        new=_contact_snapshot(values),
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("safety_contact_saved", "create", contact_id, actor_id, change_set_id)
    return _reload_contact(repository, contact_id), True


def update_contact(
    repository: ContactRepository,
    contact_id: int,
    data: ContactUpdate,
    *,
    actor_id: str,
    now: dt.datetime,
) -> ContactRecord:
    """Change a contact's date or supervisor. An unchanged contact is not written or audited."""
    values = ContactValues(contact_date=data.contact_date, supervisor_id=data.supervisor_id)
    _check_contact_date(values.contact_date, now)

    current = repository.get(contact_id, for_update=True)
    if current is None:
        repository.rollback()
        raise ContactNotFoundError(contact_id)
    if current.updated_at != data.expected_updated_at:
        repository.rollback()
        raise EditConflictError(current)
    if values == current.values:
        repository.rollback()
        return current

    # A contact may stay with a supervisor who became inactive after it was entered.
    try:
        _creditable_supervisor(
            repository,
            values,
            allow_inactive=values.supervisor_id == current.values.supervisor_id,
        )
    except ContactRuleError:
        repository.rollback()
        raise
    repository.update(contact_id, values, actor_id=actor_id, at=now)
    change_set_id = _audit(
        repository,
        action="update",
        entity_type=CONTACT_ENTITY_TYPE,
        entity_key=contact_key(contact_id),
        old=_contact_snapshot(current.values),
        new=_contact_snapshot(values),
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("safety_contact_saved", "update", contact_id, actor_id, change_set_id)
    return _reload_contact(repository, contact_id)


def delete_contact(
    repository: ContactRepository, contact_id: int, *, actor_id: str, now: dt.datetime
) -> None:
    """Delete a contact (including Undo of a +1). Its last values remain in core.audit_events."""
    current = repository.get(contact_id, for_update=True)
    if current is None:
        repository.rollback()
        raise ContactNotFoundError(contact_id)
    repository.delete(contact_id)
    change_set_id = _audit(
        repository,
        action="delete",
        entity_type=CONTACT_ENTITY_TYPE,
        entity_key=contact_key(contact_id),
        old=_contact_snapshot(current.values),
        new=None,
        actor_id=actor_id,
        now=now,
    )
    repository.commit()
    _log_saved("safety_contact_saved", "delete", contact_id, actor_id, change_set_id)


def _reload_contact(repository: ContactRepository, contact_id: int) -> ContactRecord:
    record = repository.get(contact_id)
    assert record is not None  # noqa: S101 - just written in a committed transaction
    return record


# Counts --------------------------------------------------------------------------


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])


def period(year: int, month: int | None = None) -> ContactFilter:
    """Filter for a calendar year, or one month of it."""
    if month is None:
        return ContactFilter(contact_from=dt.date(year, 1, 1), contact_to=dt.date(year, 12, 31))
    start, end = month_bounds(year, month)
    return ContactFilter(contact_from=start, contact_to=end)


def started_months(year: int, today: dt.date) -> int:
    """How many months of ``year`` have started by ``today`` (0-12)."""
    if year < today.year:
        return 12
    if year > today.year:
        return 0
    return today.month


def participation(
    supervisors: Sequence[SupervisorRecord],
    rows: Sequence[CountRow],
    *,
    year: int,
    month: int,
) -> Participation:
    """Eligible supervisors with a contact in the month, out of those eligible for it."""
    start, end = month_bounds(year, month)
    eligible = {
        s.id
        for s in supervisors
        if s.values.participation_eligible and _in_effect(s.values, start, end)
    }
    contacted = {row.supervisor_id for row in rows if row.month == month and row.count > 0}
    participating = len(eligible & contacted)
    return Participation(
        participating=participating,
        eligible=len(eligible),
        rate=participating / len(eligible) if eligible else None,
    )


def _alphabetical(supervisors: Sequence[SupervisorRecord]) -> list[SupervisorRecord]:
    return sorted(supervisors, key=lambda s: (s.values.display_name.lower(), s.id))


def build_summary(
    *,
    year: int,
    month: int | None,
    supervisors: Sequence[SupervisorRecord],
    rows: Sequence[CountRow],
) -> ContactSummaryResponse:
    per_supervisor: dict[int, int] = {}
    for row in rows:
        per_supervisor[row.supervisor_id] = per_supervisor.get(row.supervisor_id, 0) + row.count
    shown = [s for s in _alphabetical(supervisors) if s.values.active or s.id in per_supervisor]
    return ContactSummaryResponse(
        year=year,
        month=month,
        contacts=sum(row.count for row in rows),
        participation=(participation(supervisors, rows, year=year, month=month) if month else None),
        supervisors=[
            SupervisorCount(
                supervisor_id=s.id,
                display_name=s.values.display_name,
                active=s.values.active,
                contacts=per_supervisor.get(s.id, 0),
            )
            for s in shown
        ],
    )


def summarize(
    repository: ContactRepository, *, year: int, month: int | None
) -> ContactSummaryResponse:
    return build_summary(
        year=year,
        month=month,
        supervisors=repository.supervisors(),
        rows=repository.counts(period(year, month)),
    )


def build_dashboard(
    *,
    year: int,
    today: dt.date,
    supervisors: Sequence[SupervisorRecord],
    rows: Sequence[CountRow],
    years_with_data: Sequence[int],
) -> ContactDashboardResponse:
    through = started_months(year, today)
    year_start, year_end = dt.date(year, 1, 1), dt.date(year, 12, 31)
    with_contacts = {row.supervisor_id for row in rows}

    def monthly(supervisor_id: int | None = None) -> list[int | None]:
        return [
            sum(
                row.count
                for row in rows
                if row.month == month and supervisor_id in (None, row.supervisor_id)
            )
            if month <= through
            else None
            for month in MONTHS
        ]

    listed = [
        s
        for s in _alphabetical(supervisors)
        if s.id in with_contacts or _in_effect(s.values, year_start, year_end)
    ]
    dashboard_supervisors = []
    for s in listed:
        values = monthly(s.id)
        dashboard_supervisors.append(
            DashboardSupervisor(
                supervisor_id=s.id,
                display_name=s.values.display_name,
                active=s.values.active,
                monthly=values,
                total=sum(v for v in values if v is not None),
            )
        )
    totals = monthly()
    return ContactDashboardResponse(
        year=year,
        through_month=through,
        contacts=sum(v for v in totals if v is not None),
        months=[
            DashboardMonth(
                month=month,
                contacts=totals[month - 1],
                participation=(
                    participation(supervisors, rows, year=year, month=month)
                    if month <= through
                    else None
                ),
            )
            for month in MONTHS
        ],
        supervisors=dashboard_supervisors,
        years_with_data=list(years_with_data),
    )


def dashboard(
    repository: ContactRepository, *, year: int, today: dt.date
) -> ContactDashboardResponse:
    return build_dashboard(
        year=year,
        today=today,
        supervisors=repository.supervisors(),
        rows=repository.counts(period(year)),
        years_with_data=repository.years_with_contacts(),
    )
