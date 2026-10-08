"""Incident and Near Miss records: entry, corrections, history and reconciliation.

Every change is audited as ``safety.incident_record`` with key
``incident-records/<id>`` (core.audit_events), in the same transaction as the
change. ``version`` guards each change: a request carrying a stale version is
refused with the current record, and nothing is written.

Records never change the monthly totals, and saving a monthly total never
creates or removes records. Reconciliation compares the two and only warns.
"""

import calendar
import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.audit.recorder import AuditAction, AuditChange
from app.safety.records.models import EARLIEST_INCIDENT_DATE, IncidentRecord
from app.safety.records.numbers import InvalidIncidentNumberError, normalize_incident_number
from app.safety.records.repository import (
    DuplicateIncidentNumberError,
    Option,
    RecordRepository,
    RecordRow,
)
from app.safety.records.schemas import (
    MonthContext,
    MonthReconciliationOut,
    ReclassifyRequest,
    ReconciliationResponse,
    ReconciliationState,
    RecordCreate,
    RecordFields,
    RecordOut,
    RecordUpdate,
    VoidRequest,
)
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

ENTITY_TYPE = "safety.incident_record"
EVENT_TYPES = ("incident", "near_miss")
OTHER_TYPE = {"incident": "near_miss", "near_miss": "incident"}
EVENT_LABELS = {"incident": "Incident", "near_miss": "Near Miss"}
# Fields recorded in the audit trail. ``source_reference`` is included: the
# audit trail is the record's provenance; the public record schema omits it.
AUDITED_FIELDS = (
    "incident_number",
    "event_type",
    "incident_date",
    "description",
    "area_id",
    "classification_category_id",
    "status",
    "status_reason",
    "related_incident_id",
    "source",
    "source_reference",
    "version",
)


def entity_key(record_id: int) -> str:
    return f"incident-records/{record_id}"


class RecordRuleError(ValueError):
    """The request breaks a record rule. Nothing was written."""

    def __init__(self, error: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.field = field


class RecordNotFoundError(LookupError):
    pass


class RecordConflictError(RuntimeError):
    """The record changed since the client loaded it. Nothing was written."""

    def __init__(self, current: RecordRow) -> None:
        super().__init__("record changed since it was loaded")
        self.current = current


@dataclass(frozen=True)
class Actor:
    actor_id: str
    now: dt.datetime


# Reading ---------------------------------------------------------------------------


def record_out(row: RecordRow) -> RecordOut:
    r = row.record
    return RecordOut(
        id=r.id,
        incident_number=r.incident_number,
        event_type=r.event_type,  # type: ignore[arg-type]
        incident_date=r.incident_date,
        reporting_year=r.incident_date.year,
        reporting_month=r.incident_date.month,
        description=r.description,
        area_id=r.area_id,
        area_code=row.area_code,
        area_name=row.area_name,
        classification_category_id=r.classification_category_id,
        classification_code=row.classification_code,
        classification_name=row.classification_name,
        status=r.status,  # type: ignore[arg-type]
        status_reason=r.status_reason,
        related_incident_id=r.related_incident_id,
        related_incident_number=row.related_incident_number,
        source=r.source,  # type: ignore[arg-type]
        version=r.version,
        created_at=r.created_at,
        created_by=r.created_by,
        updated_at=r.updated_at,
        updated_by=r.updated_by,
    )


def audit_value(record: IncidentRecord) -> dict[str, Any]:
    values = {field: getattr(record, field) for field in AUDITED_FIELDS}
    values["incident_date"] = record.incident_date.isoformat()
    return values


def public_audit_value(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """An audit value as shown through the API: without the source location."""
    if value is None:
        return None
    return {k: v for k, v in value.items() if k != "source_reference"}


def reconciliation_state(total: int | None, documented: int) -> ReconciliationState:
    if total is None:
        return "total_unreported_with_records" if documented else "no_total_and_no_records"
    if total == 0 and documented:
        return "explicit_zero_with_records"
    if documented == total:
        return "reconciled"
    return "records_missing" if documented < total else "records_exceed_total"


def reconciliation(
    repository: RecordRepository, year: int, permissions: dict[str, bool]
) -> ReconciliationResponse:
    totals = repository.monthly_totals(year)
    documented = repository.documented_counts(year)
    months = []
    for event_type in EVENT_TYPES:
        for month in range(1, 13):
            total = totals.get((event_type, month))
            count = documented.get((event_type, month), 0)
            months.append(
                MonthReconciliationOut(
                    month=month,
                    event_type=event_type,  # type: ignore[arg-type]
                    monthly_total=total,
                    documented=count,
                    state=reconciliation_state(total, count),
                )
            )
    return ReconciliationResponse(year=year, months=months, **permissions)


# Validation ------------------------------------------------------------------------


def _option(options: list[Option], option_id: int) -> Option | None:
    return next((o for o in options if o.id == option_id), None)


def _validated(
    repository: RecordRepository,
    fields: RecordFields,
    context: MonthContext,
    *,
    today: dt.date,
    current: IncidentRecord | None = None,
) -> dict[str, Any]:
    try:
        number = normalize_incident_number(fields.incident_number)
    except InvalidIncidentNumberError as error:
        raise RecordRuleError(
            "invalid_incident_number", str(error), field="incidentNumber"
        ) from None

    day = fields.incident_date
    if day < EARLIEST_INCIDENT_DATE:
        raise RecordRuleError("invalid_date", "The date is before 2000.", field="incidentDate")
    if day > today:
        raise RecordRuleError(
            "future_date", "The date of the incident cannot be in the future.", field="incidentDate"
        )
    if context.reporting_year is not None and context.reporting_month is not None:
        year, month = context.reporting_year, context.reporting_month
        if (day.year, day.month) != (year, month):
            raise RecordRuleError(
                "date_outside_month",
                f"The date must fall in {calendar.month_name[month]} {year}. "
                "Records are never moved to another month.",
                field="incidentDate",
            )

    description = fields.description.strip()
    if not description:
        raise RecordRuleError("blank_description", "Enter a description.", field="description")

    if fields.area_id is not None:
        area = _option(repository.areas(), fields.area_id)
        unchanged = current is not None and current.area_id == fields.area_id
        if area is None or not (area.active or unchanged):
            raise RecordRuleError("invalid_area", "Choose an active area.", field="areaId")
    category_id = fields.classification_category_id
    if category_id is not None:
        category = _option(repository.classifications(), category_id)
        unchanged = current is not None and current.classification_category_id == category_id
        if category is None or not (category.active or unchanged):
            raise RecordRuleError(
                "invalid_classification",
                "Choose an active Incident Classification.",
                field="classificationCategoryId",
            )

    if number is not None:
        owner = repository.number_owner(number)
        if owner is not None and (current is None or owner != current.id):
            raise RecordRuleError(
                "duplicate_incident_number",
                f"{number} is already used by another record.",
                field="incidentNumber",
            )

    return {
        "incident_number": number,
        "incident_date": day,
        "description": description,
        "area_id": fields.area_id,
        "classification_category_id": category_id,
    }


def _duplicate(error: DuplicateIncidentNumberError) -> RecordRuleError:
    return RecordRuleError(
        "duplicate_incident_number",
        f"{error.number} is already used by another record.",
        field="incidentNumber",
    )


def _locked_active(repository: RecordRepository, record_id: int, version: int) -> IncidentRecord:
    record = repository.lock(record_id)
    if record is None:
        raise RecordNotFoundError(record_id)
    if record.version != version:
        current = repository.get(record_id)
        assert current is not None  # noqa: S101 - locked above
        raise RecordConflictError(current)
    if record.status != "active":
        raise RecordRuleError(
            "record_inactive",
            f"This record is {record.status}; only active records can be changed.",
        )
    return record


def _change(action: AuditAction, record_id: int, old: dict | None, new: dict | None) -> AuditChange:
    return AuditChange(
        action=action,
        entity_type=ENTITY_TYPE,
        entity_key=entity_key(record_id),
        old_value=old,
        new_value=new,
    )


def _log(event: str, record_id: int, actor: Actor, change_set: uuid.UUID) -> None:
    logger.info(
        "event=%s key=%s user=%s change_set=%s",
        event,
        entity_key(record_id),
        actor.actor_id,
        change_set,
    )


def _audited_insert(
    repository: RecordRepository, values: dict[str, Any], actor: Actor, change_set: uuid.UUID
) -> int:
    try:
        record_id = repository.insert(values, actor_id=actor.actor_id, at=actor.now)
    except DuplicateIncidentNumberError as error:
        raise _duplicate(error) from None
    created = repository.lock(record_id)
    assert created is not None  # noqa: S101 - inserted above
    repository.record_audit(
        actor_id=actor.actor_id,
        change_set_id=change_set,
        at=actor.now,
        changes=[_change("create", record_id, None, audit_value(created))],
    )
    return record_id


# Writing ---------------------------------------------------------------------------


def create(
    repository: RecordRepository,
    request: RecordCreate,
    actor: Actor,
    *,
    source: str = "manual",
    source_reference: str | None = None,
    status: str = "active",
    status_reason: str | None = None,
) -> RecordRow:
    """Create a record. ``source``, ``source_reference`` and an inactive status
    are set only by the reviewed legacy import."""
    change_set = uuid.uuid4()
    try:
        values = _validated(repository, request, request, today=site_today(actor.now))
        values |= {
            "event_type": request.event_type,
            "source": source,
            "source_reference": source_reference,
            "status": status,
            "status_reason": status_reason,
        }
        record_id = _audited_insert(repository, values, actor, change_set)
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("safety_incident_record_created", record_id, actor, change_set)
    row = repository.get(record_id)
    assert row is not None  # noqa: S101 - committed above
    return row


def update(
    repository: RecordRepository, record_id: int, request: RecordUpdate, actor: Actor
) -> RecordRow:
    """Edit an active record's fields. Unchanged values write nothing."""
    change_set = uuid.uuid4()
    try:
        record = _locked_active(repository, record_id, request.version)
        values = _validated(
            repository, request, request, today=site_today(actor.now), current=record
        )
        changed = {k: v for k, v in values.items() if getattr(record, k) != v}
        if not changed:
            repository.rollback()
            row = repository.get(record_id)
            assert row is not None  # noqa: S101 - exists
            return row
        before = audit_value(record)
        try:
            repository.update(
                record_id, changed, version=record.version, actor_id=actor.actor_id, at=actor.now
            )
        except DuplicateIncidentNumberError as error:
            raise _duplicate(error) from None
        after = repository.lock(record_id)
        assert after is not None  # noqa: S101 - updated above
        repository.record_audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[_change("update", record_id, before, audit_value(after))],
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("safety_incident_record_updated", record_id, actor, change_set)
    row = repository.get(record_id)
    assert row is not None  # noqa: S101 - committed above
    return row


def void(
    repository: RecordRepository, record_id: int, request: VoidRequest, actor: Actor
) -> RecordRow:
    """Mark a record voided. It is kept and excluded from active counts."""
    change_set = uuid.uuid4()
    reason = request.reason.strip()
    if not reason:
        raise RecordRuleError("blank_reason", "Enter the reason for voiding.", field="reason")
    try:
        record = _locked_active(repository, record_id, request.version)
        before = audit_value(record)
        repository.update(
            record_id,
            {"status": "voided", "status_reason": reason},
            version=record.version,
            actor_id=actor.actor_id,
            at=actor.now,
        )
        after = repository.lock(record_id)
        assert after is not None  # noqa: S101 - updated above
        repository.record_audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[_change("update", record_id, before, audit_value(after))],
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("safety_incident_record_voided", record_id, actor, change_set)
    row = repository.get(record_id)
    assert row is not None  # noqa: S101 - committed above
    return row


def reclassify(
    repository: RecordRepository,
    record_id: int,
    request: ReclassifyRequest,
    actor: Actor,
    *,
    source: str = "manual",
    source_reference: str | None = None,
) -> tuple[RecordRow, RecordRow]:
    """Reclassify a record as the other event type. The original is kept with
    status ``reclassified`` and points at its active replacement."""
    change_set = uuid.uuid4()
    reason = request.reason.strip()
    if not reason:
        raise RecordRuleError("blank_reason", "Enter the reason for reclassifying.", field="reason")
    try:
        record = _locked_active(repository, record_id, request.version)
        new_type = OTHER_TYPE[record.event_type]
        if request.replacement is not None:
            values = _validated(
                repository, request.replacement, MonthContext(), today=site_today(actor.now)
            )
            values |= {
                "event_type": new_type,
                "source": source,
                "source_reference": source_reference,
                "status": "active",
                "status_reason": None,
            }
            replacement_id = _audited_insert(repository, values, actor, change_set)
        else:
            assert request.replacement_id is not None  # noqa: S101 - validated by the schema
            replacement = repository.lock(request.replacement_id)
            if (
                replacement is None
                or replacement.id == record.id
                or replacement.status != "active"
                or replacement.event_type != new_type
            ):
                raise RecordRuleError(
                    "invalid_replacement",
                    f"The replacement must be an active {EVENT_LABELS[new_type]} record.",
                    field="replacementId",
                )
            replacement_id = replacement.id
        before = audit_value(record)
        repository.update(
            record_id,
            {
                "status": "reclassified",
                "status_reason": reason,
                "related_incident_id": replacement_id,
            },
            version=record.version,
            actor_id=actor.actor_id,
            at=actor.now,
        )
        after = repository.lock(record_id)
        assert after is not None  # noqa: S101 - updated above
        repository.record_audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[_change("update", record_id, before, audit_value(after))],
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("safety_incident_record_reclassified", record_id, actor, change_set)
    original = repository.get(record_id)
    new = repository.get(replacement_id)
    assert original is not None and new is not None  # noqa: S101 - committed above
    return original, new
