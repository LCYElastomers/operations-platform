"""Annual Behavior counts: loading, audited saves and the Pareto.

A missing count is unreported, never 0. Percentages are calculated here and
never stored. The share of Incident reports uses the stored Incident total as
the denominator; tags overlap, so those shares may sum above 100%.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.audit.recorder import AuditChange
from app.safety.behavior.repository import BehaviorCategoryDefinition, BehaviorRepository
from app.safety.behavior.schemas import (
    BehaviorChange,
    BehaviorConflict,
    BehaviorCountRow,
    BehaviorCountsResponse,
)
from app.safety.schemas import BehaviorAnalyticsOut, BehaviorParetoRowOut
from app.safety.service import total

logger = logging.getLogger(__name__)

AUDIT_ENTITY_TYPE = "safety.annual_behavior_count"


class UnknownBehaviorCategoryError(ValueError):
    def __init__(self, category_ids: Sequence[int]) -> None:
        super().__init__("unknown behavior category")
        self.category_ids = sorted(set(category_ids))


class BehaviorConflictError(RuntimeError):
    def __init__(self, conflicts: Sequence[BehaviorConflict]) -> None:
        super().__init__("behavior edit conflict")
        self.conflicts = list(conflicts)


def load_counts(
    repository: BehaviorRepository, *, year: int, can_edit: bool
) -> BehaviorCountsResponse:
    categories = repository.categories()
    stored = repository.counts(year)
    rows = [
        BehaviorCountRow(id=c.id, code=c.code, name=c.name, value=stored.get(c.id))
        for c in categories
    ]
    return BehaviorCountsResponse(
        year=year,
        can_edit=can_edit,
        categories=rows,
        total=total(row.value for row in rows),
        years_with_data=repository.years_with_counts(),
    )


def entity_key(category: BehaviorCategoryDefinition, year: int) -> str:
    return f"incidents/behavior/{category.code}/{year}"


@dataclass(frozen=True)
class BehaviorSaveOutcome:
    changed_categories: int
    change_set_id: uuid.UUID | None


def save_counts(
    repository: BehaviorRepository,
    *,
    year: int,
    changes: Sequence[BehaviorChange],
    actor_id: str,
    now: dt.datetime,
) -> BehaviorSaveOutcome:
    """Apply annual count changes atomically, one audit event per changed category.

    Unchanged values are ignored. If any stored value differs from the client's
    ``previous_value``, nothing is written and ``BehaviorConflictError`` is raised.
    """
    owners = {category.id: category for category in repository.categories()}
    unknown = [change.category_id for change in changes if change.category_id not in owners]
    if unknown:
        raise UnknownBehaviorCategoryError(unknown)

    repository.lock_year(year)
    current = repository.counts(year)
    conflicts = [
        BehaviorConflict(
            category_id=change.category_id, current_value=current.get(change.category_id)
        )
        for change in changes
        if current.get(change.category_id) != change.previous_value
    ]
    if conflicts:
        repository.rollback()
        raise BehaviorConflictError(conflicts)

    upserts: dict[int, int] = {}
    deletes: list[int] = []
    audit: list[AuditChange] = []
    for change in changes:
        old = current.get(change.category_id)
        if old == change.value:
            continue
        if change.value is None:
            deletes.append(change.category_id)
            action = "delete"
        else:
            upserts[change.category_id] = change.value
            action = "create" if old is None else "update"
        audit.append(
            AuditChange(
                action=action,
                entity_type=AUDIT_ENTITY_TYPE,
                entity_key=entity_key(owners[change.category_id], year),
                old_value=None if old is None else {"value": old},
                new_value=None if change.value is None else {"value": change.value},
            )
        )

    if not audit:
        repository.rollback()
        return BehaviorSaveOutcome(changed_categories=0, change_set_id=None)

    change_set_id = uuid.uuid4()
    repository.write(year=year, upserts=upserts, deletes=deletes, actor_id=actor_id, at=now)
    repository.record_audit(actor_id=actor_id, change_set_id=change_set_id, at=now, changes=audit)
    repository.commit()
    logger.info(
        "event=safety_behavior_saved year=%s user=%s change_set=%s "
        "created=%s updated=%s deleted=%s",
        year,
        actor_id,
        change_set_id,
        sum(1 for a in audit if a.action == "create"),
        sum(1 for a in audit if a.action == "update"),
        sum(1 for a in audit if a.action == "delete"),
    )
    return BehaviorSaveOutcome(changed_categories=len(audit), change_set_id=change_set_id)


def _share(part: int, whole: int | None) -> float | None:
    return part / whole if whole else None


def build_pareto(
    *,
    year: int,
    categories: Sequence[BehaviorCategoryDefinition],
    counts: Mapping[int, int],
    incident_months: Sequence[int | None],
) -> BehaviorAnalyticsOut:
    """The Behavior Pareto for one year.

    ``incident_months`` is the stored monthly Incident total for the whole year;
    its reported months sum to the Incident reports denominator.
    """
    reported = sorted(
        (c for c in categories if c.id in counts),
        key=lambda c: (-counts[c.id], c.display_order, c.id),
    )
    tags = total(counts[c.id] for c in reported)
    incident_reports = total(incident_months)
    rows: list[BehaviorParetoRowOut] = []
    running = 0
    for category in reported:
        count = counts[category.id]
        running += count
        rows.append(
            BehaviorParetoRowOut(
                code=category.code,
                name=category.name,
                count=count,
                share_of_tags=_share(count, tags),
                share_of_incident_reports=_share(count, incident_reports),
                cumulative_share_of_tags=_share(running, tags),
            )
        )
    return BehaviorAnalyticsOut(
        year=year,
        available=bool(rows),
        categories=rows,
        unreported=[c.name for c in categories if c.id not in counts],
        total_tags=tags,
        incident_reports=incident_reports,
        incident_reports_months_reported=sum(1 for v in incident_months if v is not None),
        behaviors_per_incident_report=(
            _share(tags, incident_reports) if tags is not None else None
        ),
    )
