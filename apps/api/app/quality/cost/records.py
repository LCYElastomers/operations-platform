"""Quality Cost records: entry, edits, history.

Every change is audited as ``quality.cost_record`` with key
``cost-records/<id>`` (core.audit_events), in the same transaction as the
change. ``version`` guards each edit: a request carrying a stale version is
refused with the current record, and nothing is written. Records are never
deleted.
"""

import datetime as dt
import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.audit.recorder import AuditAction, AuditChange
from app.auth import people
from app.core.permissions import Permission
from app.quality.cost import calculations
from app.quality.cost.classification import (
    CATEGORY_BY_CODE,
    CONFIRMED_FINANCIAL,
    COQ_CLASSES,
    FINANCIAL_STATUSES,
    OPERATIONAL_STATUSES,
    REFERENCE_TYPES,
    category_label,
    quality_group,
)
from app.quality.cost.models import (
    EARLIEST_RECORD_DATE,
    IDENTIFICATION_FIELDS,
    MONEY_FIELDS,
    CostRecord,
)
from app.quality.cost.repository import CostRepository, RecordRow, Reference
from app.quality.cost.schemas import (
    CostRecordCreate,
    CostRecordFields,
    CostRecordOut,
    CostRecordUpdate,
    ReferenceOut,
)
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

ENTITY_TYPE = "quality.cost_record"
RECORD_NUMBER_PREFIX = "QC-"
_RECORD_NUMBER = re.compile(r"^\s*QC-?0*([0-9]{1,15})\s*$", re.IGNORECASE)
# Edited through the form; the source fields are set by the import only.
EDITABLE_FIELDS = (
    "record_date",
    "title",
    "area_id",
    "coq_class",
    "category_code",
    "description",
    *IDENTIFICATION_FIELDS,
    "owner",
    "owner_user_id",
    "notes",
    *MONEY_FIELDS,
    "financial_status",
    "status",
    "due_date",
    "date_closed",
    "resolution_notes",
)
# The audit trail is the record's provenance, so it includes the source
# reference; the public record schema omits it.
AUDITED_FIELDS = (*EDITABLE_FIELDS, "source", "source_key", "source_reference", "version")


def entity_key(record_id: int) -> str:
    return f"cost-records/{record_id}"


def record_number(record_id: int) -> str:
    return f"{RECORD_NUMBER_PREFIX}{record_id:05d}"


def parse_record_number(text: str) -> int | None:
    """The record id of a number such as ``QC-00042`` or ``qc42``; None otherwise."""
    match = _RECORD_NUMBER.match(text)
    return int(match.group(1)) if match else None


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


class RecordForbiddenError(PermissionError):
    """The user may edit the record but not make this change. Nothing was written."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Actor:
    """Who makes a change. ``permissions`` is None for system actors (imports),
    which are not subject to user permission rules."""

    actor_id: str
    now: dt.datetime
    permissions: frozenset[Permission] | None = None
    user_id: uuid.UUID | None = None
    name: str | None = None

    def require(self, permission: Permission, message: str) -> None:
        if self.permissions is not None and permission not in self.permissions:
            raise RecordForbiddenError(message)


# Reading ---------------------------------------------------------------------------


def record_out(
    row: RecordRow, today: dt.date, names: dict[str, str] | None = None
) -> CostRecordOut:
    """``names``: display names of users (``people.display_names``) for created/updated by."""
    r = row.record
    names = names or {}
    return CostRecordOut(
        id=r.id,
        record_number=record_number(r.id),
        record_date=r.record_date,
        title=r.title,
        area_id=r.area_id,
        area_name=row.area_name,
        coq_class=r.coq_class,  # type: ignore[arg-type]
        coq_class_label=COQ_CLASSES[r.coq_class],  # type: ignore[index]
        quality_group=quality_group(r.coq_class),
        category_code=r.category_code,
        category_label=category_label(r.category_code),
        description=r.description,
        product=r.product,
        campaign=r.campaign,
        lot=r.lot,
        location=r.location,
        process=r.process,
        equipment=r.equipment,
        counterparty=r.counterparty,
        owner=r.owner,
        owner_user_id=r.owner_user_id,
        notes=r.notes,
        material_cost=r.material_cost,
        labor_cost=r.labor_cost,
        production_cost=r.production_cost,
        testing_cost=r.testing_cost,
        maintenance_cost=r.maintenance_cost,
        freight_cost=r.freight_cost,
        disposal_cost=r.disposal_cost,
        customer_cost=r.customer_cost,
        other_cost=r.other_cost,
        total_cost=calculations.record_total(r),
        financial_status=r.financial_status,  # type: ignore[arg-type]
        financial_status_label=FINANCIAL_STATUSES[r.financial_status],  # type: ignore[index]
        cost_confirmed=calculations.is_confirmed(r),
        status=r.status,  # type: ignore[arg-type]
        status_label=OPERATIONAL_STATUSES[r.status],  # type: ignore[index]
        due_date=r.due_date,
        overdue=calculations.is_overdue(r, today),
        date_closed=r.date_closed,
        days_open=calculations.days_open(r, today),
        resolution_notes=r.resolution_notes,
        recovered_cost=r.recovered_cost,
        avoided_cost=r.avoided_cost,
        net_cost=calculations.record_net(r),
        references=[
            ReferenceOut(
                type=ref.type,
                type_label=REFERENCE_TYPES.get(ref.type, ref.type),
                key=ref.key,
                label=ref.label,
            )
            for ref in row.references
        ],
        source=r.source,  # type: ignore[arg-type]
        version=r.version,
        created_at=r.created_at,
        created_by=r.created_by,
        created_by_name=people.actor_label(r.created_by, names),
        updated_at=r.updated_at,
        updated_by=r.updated_by,
        updated_by_name=people.actor_label(r.updated_by, names),
    )


def actor_ids(rows: Any) -> list[str]:
    return [a for row in rows for a in (row.record.created_by, row.record.updated_by)]


def _audit_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def audit_value(record: CostRecord, references: tuple[Reference, ...]) -> dict[str, Any]:
    values = {field: _audit_scalar(getattr(record, field)) for field in AUDITED_FIELDS}
    values["references"] = [{"type": r.type, "key": r.key, "label": r.label} for r in references]
    return values


def public_audit_value(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """An audit value as shown through the API: without the source location."""
    if value is None:
        return None
    return {k: v for k, v in value.items() if k != "source_reference"}


# Validation ------------------------------------------------------------------------


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validated(
    repository: CostRepository,
    fields: CostRecordFields,
    *,
    today: dt.date,
    current: CostRecord | None = None,
) -> tuple[dict[str, Any], tuple[Reference, ...]]:
    day = fields.record_date
    if day < EARLIEST_RECORD_DATE:
        raise RecordRuleError("invalid_date", "The date is before 2000.", field="recordDate")
    if day > today:
        raise RecordRuleError(
            "future_date", "The date cannot be in the future.", field="recordDate"
        )

    title = _text(fields.title)
    if title is None:
        raise RecordRuleError("blank_title", "Enter a short title.", field="title")
    description = _text(fields.description)
    if description is None:
        raise RecordRuleError("blank_description", "Describe what happened.", field="description")

    imported = current is not None and current.source == "legacy_import"
    if fields.area_id is None:
        if not (imported and current is not None and current.area_id is None):
            raise RecordRuleError("area_required", "Choose an area.", field="areaId")
    else:
        area = next((a for a in repository.areas() if a.id == fields.area_id), None)
        unchanged = current is not None and current.area_id == fields.area_id
        if area is None or not (area.active or unchanged):
            raise RecordRuleError("invalid_area", "Choose an active area.", field="areaId")

    category = CATEGORY_BY_CODE.get(fields.category_code)
    if category is None or category.coq_class != fields.coq_class:
        raise RecordRuleError(
            "invalid_category",
            f"Choose a {COQ_CLASSES[fields.coq_class]} category.",
            field="categoryCode",
        )

    if fields.due_date is not None and fields.due_date < day:
        raise RecordRuleError(
            "due_before_date", "The due date cannot be before the date.", field="dueDate"
        )
    if fields.status == "closed":
        if fields.date_closed is None:
            raise RecordRuleError(
                "date_closed_required", "Enter the date closed.", field="dateClosed"
            )
        if fields.date_closed < day:
            raise RecordRuleError(
                "closed_before_date",
                "The date closed cannot be before the date.",
                field="dateClosed",
            )
        if fields.date_closed > today:
            raise RecordRuleError(
                "future_date_closed", "The date closed cannot be in the future.", field="dateClosed"
            )
    elif fields.date_closed is not None:
        raise RecordRuleError(
            "date_closed_not_closed",
            "Only a closed record has a date closed. Set the status to Closed or clear the date.",
            field="dateClosed",
        )

    references: list[Reference] = []
    for reference in fields.references:
        key = _text(reference.key)
        if reference.type not in REFERENCE_TYPES:
            raise RecordRuleError(
                "invalid_reference", "Unknown reference type.", field="references"
            )
        if key is None:
            continue
        if any(r.type == reference.type and r.key == key for r in references):
            continue
        references.append(Reference(reference.type, key, _text(reference.label)))

    try:
        owner = people.resolve(
            lambda: repository.session,
            user_id=fields.owner_user_id,
            name=fields.owner,
            current=people.Person(current.owner, current.owner_user_id)
            if current
            else people.NOBODY,
        )
    except people.PersonChoiceError:
        raise RecordRuleError(
            "invalid_owner", "Choose the owner from the list of active users.", field="owner"
        ) from None

    values: dict[str, Any] = {
        "record_date": day,
        "title": title,
        "area_id": fields.area_id,
        "coq_class": fields.coq_class,
        "category_code": fields.category_code,
        "description": description,
        **{f: _text(getattr(fields, f)) for f in IDENTIFICATION_FIELDS},
        "owner": owner.name,
        "owner_user_id": owner.user_id,
        "notes": _text(fields.notes),
        **{f: getattr(fields, f) for f in MONEY_FIELDS},
        "financial_status": fields.financial_status,
        "status": fields.status,
        "due_date": fields.due_date,
        "date_closed": fields.date_closed,
        "resolution_notes": _text(fields.resolution_notes),
    }
    return values, tuple(references)


def _comparable(value: Any) -> Any:
    return value.normalize() if isinstance(value, Decimal) else value


def check_permissions(values: dict[str, Any], current: CostRecord | None, actor: Actor) -> None:
    """Changes that need more than ``qualityCost.edit``: the owner, confirming
    (or un-confirming) the financial status, and closing or reopening."""
    owner = (values["owner"], values["owner_user_id"])
    if owner != ((current.owner, current.owner_user_id) if current else (None, None)):
        actor.require(
            Permission.QUALITY_COST_ASSIGN, "Changing the owner needs qualityCost.assign."
        )
    before_financial = current.financial_status if current else None
    if values["financial_status"] != before_financial and (
        values["financial_status"] in CONFIRMED_FINANCIAL or before_financial in CONFIRMED_FINANCIAL
    ):
        actor.require(
            Permission.QUALITY_COST_CONFIRM_FINANCIAL,
            "Confirming a cost (or undoing it) needs qualityCost.confirmFinancial.",
        )
    before_status = current.status if current else None
    if (values["status"] == "closed") != (before_status == "closed") and (
        current is not None or values["status"] == "closed"
    ):
        actor.require(
            Permission.QUALITY_COST_CLOSE, "Closing or reopening a record needs qualityCost.close."
        )


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


# Writing ---------------------------------------------------------------------------


def insert_audited(
    repository: CostRepository,
    values: dict[str, Any],
    references: tuple[Reference, ...],
    actor: Actor,
    change_set: uuid.UUID,
) -> int:
    """Insert a record and its references and audit them; the caller commits."""
    record_id = repository.insert_record(values, actor_id=actor.actor_id, at=actor.now)
    repository.replace_references(record_id, references, actor_id=actor.actor_id, at=actor.now)
    created = repository.lock_record(record_id)
    assert created is not None  # noqa: S101 - inserted above
    repository.record_audit(
        actor_id=actor.actor_id,
        change_set_id=change_set,
        at=actor.now,
        changes=[_change("create", record_id, None, audit_value(created, references))],
    )
    return record_id


def create(repository: CostRepository, request: CostRecordCreate, actor: Actor) -> RecordRow:
    change_set = uuid.uuid4()
    try:
        values, references = _validated(repository, request, today=_today(actor))
        check_permissions(values, None, actor)
        record_id = insert_audited(
            repository, {**values, "source": "manual"}, references, actor, change_set
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_cost_record_created", record_id, actor, change_set)
    row = repository.get(record_id)
    assert row is not None  # noqa: S101 - committed above
    return row


def update(
    repository: CostRepository, record_id: int, request: CostRecordUpdate, actor: Actor
) -> RecordRow:
    """Edit a record. Unchanged values write nothing."""
    change_set = uuid.uuid4()
    try:
        record = repository.lock_record(record_id)
        if record is None:
            raise RecordNotFoundError(record_id)
        if record.version != request.version:
            current = repository.get(record_id)
            assert current is not None  # noqa: S101 - locked above
            raise RecordConflictError(current)
        values, references = _validated(repository, request, today=_today(actor), current=record)
        check_permissions(values, record, actor)
        before_references = repository.references_of(record_id)
        changed = {
            k: v for k, v in values.items() if _comparable(getattr(record, k)) != _comparable(v)
        }
        references_changed = before_references != references
        if not changed and not references_changed:
            repository.rollback()
            row = repository.get(record_id)
            assert row is not None  # noqa: S101 - exists
            return row
        before = audit_value(record, before_references)
        repository.update_record(
            record_id, changed, version=record.version, actor_id=actor.actor_id, at=actor.now
        )
        if references_changed:
            repository.replace_references(
                record_id, references, actor_id=actor.actor_id, at=actor.now
            )
        after = repository.lock_record(record_id)
        assert after is not None  # noqa: S101 - updated above
        repository.record_audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[_change("update", record_id, before, audit_value(after, references))],
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_cost_record_updated", record_id, actor, change_set)
    row = repository.get(record_id)
    assert row is not None  # noqa: S101 - committed above
    return row


def _today(actor: Actor) -> dt.date:
    return site_today(actor.now)
