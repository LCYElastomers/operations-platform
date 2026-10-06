"""Safety monthly metric rules: grid assembly, calculated YTD, and audited saves.

YTD is the sum of a category's reported months, or null when nothing is
reported. Unreported (null) is never treated as 0. Categories are never summed
across a section: Incident and Near Miss are explicit source metrics, not the
sum of Incident Classification.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.audit.recorder import AuditChange
from app.safety.repository import (
    CategoryDefinition,
    Cell,
    SafetyMetricsRepository,
    SectionDefinition,
    StoredValues,
)
from app.safety.schemas import (
    CellChange,
    CellConflict,
    MetricCategoryRow,
    MetricSectionBlock,
    MonthlyMetricsResponse,
)

logger = logging.getLogger(__name__)

MONTHS = range(1, 13)
AUDIT_ENTITY_TYPE = "safety.monthly_metric_value"


class UnknownCategoryError(ValueError):
    """A change referenced a category that is not an active category of the metric set."""

    def __init__(self, category_ids: Sequence[int]) -> None:
        super().__init__("unknown category")
        self.category_ids = sorted(set(category_ids))


class EditConflictError(RuntimeError):
    """Stored values changed since the client loaded them. Nothing was written."""

    def __init__(self, conflicts: Sequence[CellConflict]) -> None:
        super().__init__("edit conflict")
        self.conflicts = list(conflicts)


def total(values: Iterable[int | None]) -> int | None:
    reported = [value for value in values if value is not None]
    return sum(reported) if reported else None


def build_metrics(
    *,
    metric_set: str,
    year: int,
    sections: Sequence[SectionDefinition],
    stored: StoredValues,
    years_with_data: Sequence[int],
    can_edit: bool,
) -> MonthlyMetricsResponse:
    blocks = []
    for section in sections:
        rows = []
        for category in section.categories:
            values = [stored.get((category.id, month)) for month in MONTHS]
            rows.append(
                MetricCategoryRow(
                    id=category.id,
                    code=category.code,
                    name=category.name,
                    values=values,
                    ytd=total(values),
                )
            )
        blocks.append(
            MetricSectionBlock(id=section.id, code=section.code, name=section.name, categories=rows)
        )
    return MonthlyMetricsResponse(
        metric_set=metric_set,
        year=year,
        can_edit=can_edit,
        sections=blocks,
        years_with_data=list(years_with_data),
    )


def category_ids(sections: Sequence[SectionDefinition]) -> list[int]:
    return [category.id for section in sections for category in section.categories]


def load_metrics(
    repository: SafetyMetricsRepository, *, metric_set: str, year: int, can_edit: bool
) -> MonthlyMetricsResponse:
    sections = repository.sections(metric_set)
    ids = category_ids(sections)
    return build_metrics(
        metric_set=metric_set,
        year=year,
        sections=sections,
        stored=repository.values(ids, year),
        years_with_data=repository.years_with_values(ids),
        can_edit=can_edit,
    )


def entity_key(
    metric_set: str,
    section: SectionDefinition,
    category: CategoryDefinition,
    year: int,
    month: int,
) -> str:
    return f"{metric_set}/{section.code}/{category.code}/{year}-{month:02d}"


@dataclass(frozen=True)
class SaveOutcome:
    changed_cells: int
    change_set_id: uuid.UUID | None


def save_changes(
    repository: SafetyMetricsRepository,
    *,
    metric_set: str,
    year: int,
    changes: Sequence[CellChange],
    actor_id: str,
    now: dt.datetime,
) -> SaveOutcome:
    """Apply cell changes atomically, with one audit event per changed cell.

    Changes that do not alter the stored value are ignored. If any cell's
    stored value differs from the client's ``previous_value``, nothing is
    written and ``EditConflictError`` lists the conflicting cells.
    """
    sections = repository.sections(metric_set)
    owners = {
        category.id: (section, category) for section in sections for category in section.categories
    }
    unknown = [change.category_id for change in changes if change.category_id not in owners]
    if unknown:
        raise UnknownCategoryError(unknown)

    repository.lock_year(metric_set, year)
    current = repository.values(sorted({change.category_id for change in changes}), year)

    conflicts = [
        CellConflict(
            category_id=change.category_id,
            month=change.month,
            current_value=current.get((change.category_id, change.month)),
        )
        for change in changes
        if current.get((change.category_id, change.month)) != change.previous_value
    ]
    if conflicts:
        repository.rollback()
        raise EditConflictError(conflicts)

    upserts: dict[Cell, int] = {}
    deletes: list[Cell] = []
    audit: list[AuditChange] = []
    for change in changes:
        cell = (change.category_id, change.month)
        old = current.get(cell)
        if old == change.value:
            continue
        if change.value is None:
            deletes.append(cell)
            action = "delete"
        else:
            upserts[cell] = change.value
            action = "create" if old is None else "update"
        section, category = owners[change.category_id]
        audit.append(
            AuditChange(
                action=action,
                entity_type=AUDIT_ENTITY_TYPE,
                entity_key=entity_key(metric_set, section, category, year, change.month),
                old_value=None if old is None else {"value": old},
                new_value=None if change.value is None else {"value": change.value},
            )
        )

    if not audit:
        repository.rollback()
        return SaveOutcome(changed_cells=0, change_set_id=None)

    change_set_id = uuid.uuid4()
    repository.write(year=year, upserts=upserts, deletes=deletes, actor_id=actor_id, at=now)
    repository.record_audit(actor_id=actor_id, change_set_id=change_set_id, at=now, changes=audit)
    repository.commit()
    logger.info(
        "event=safety_metrics_saved metric_set=%s year=%s user=%s change_set=%s "
        "created=%s updated=%s deleted=%s",
        metric_set,
        year,
        actor_id,
        change_set_id,
        sum(1 for a in audit if a.action == "create"),
        sum(1 for a in audit if a.action == "update"),
        sum(1 for a in audit if a.action == "delete"),
    )
    return SaveOutcome(changed_cells=len(audit), change_set_id=change_set_id)
