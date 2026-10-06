"""Database access for Safety monthly metrics."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.safety.models import (
    MONTHLY_VALUE_IDENTITY_CONSTRAINT,
    MetricCategory,
    MetricSection,
    MonthlyMetricValue,
)


@dataclass(frozen=True)
class CategoryDefinition:
    id: int
    code: str
    name: str


@dataclass(frozen=True)
class SectionDefinition:
    id: int
    code: str
    name: str
    categories: tuple[CategoryDefinition, ...]


# (category_id, month) -> stored value
Cell = tuple[int, int]
StoredValues = dict[Cell, int]


class SafetyMetricsRepository(Protocol):
    def sections(self, metric_set: str) -> list[SectionDefinition]:
        """Active sections of a metric set and their active categories, in display order."""
        ...

    def values(self, category_ids: Sequence[int], year: int) -> StoredValues: ...

    def years_with_values(self, category_ids: Sequence[int]) -> list[int]: ...

    def lock_year(self, metric_set: str, year: int) -> None:
        """Serialize saves for one metric set and year until the transaction ends."""
        ...

    def write(
        self,
        *,
        year: int,
        upserts: dict[Cell, int],
        deletes: Sequence[Cell],
        actor_id: str,
        at: dt.datetime,
    ) -> None: ...

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class DatabaseSafetyMetricsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def sections(self, metric_set: str) -> list[SectionDefinition]:
        s, c = MetricSection, MetricCategory
        rows = self._session.execute(
            select(s.id, s.code, s.name, c.id, c.code, c.name)
            .join(c, c.section_id == s.id)
            .where(s.metric_set == metric_set, s.active.is_(True), c.active.is_(True))
            .order_by(s.display_order, s.id, c.display_order, c.id)
        ).all()
        sections: dict[int, tuple[str, str, list[CategoryDefinition]]] = {}
        for section_id, section_code, section_name, category_id, code, name in rows:
            entry = sections.setdefault(section_id, (section_code, section_name, []))
            entry[2].append(CategoryDefinition(id=category_id, code=code, name=name))
        return [
            SectionDefinition(id=section_id, code=code, name=name, categories=tuple(categories))
            for section_id, (code, name, categories) in sections.items()
        ]

    def values(self, category_ids: Sequence[int], year: int) -> StoredValues:
        if not category_ids:
            return {}
        v = MonthlyMetricValue
        rows = self._session.execute(
            select(v.category_id, v.reporting_month, v.value).where(
                v.category_id.in_(category_ids), v.reporting_year == year
            )
        ).all()
        return {(row.category_id, row.reporting_month): row.value for row in rows}

    def years_with_values(self, category_ids: Sequence[int]) -> list[int]:
        if not category_ids:
            return []
        v = MonthlyMetricValue
        years = self._session.scalars(
            select(v.reporting_year)
            .where(v.category_id.in_(category_ids))
            .distinct()
            .order_by(v.reporting_year)
        ).all()
        return list(years)

    def lock_year(self, metric_set: str, year: int) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"safety.monthly_metric_values:{metric_set}:{year}"},
        )

    def write(
        self,
        *,
        year: int,
        upserts: dict[Cell, int],
        deletes: Sequence[Cell],
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        v = MonthlyMetricValue
        if upserts:
            statement = insert(v).values(
                [
                    {
                        "category_id": category_id,
                        "reporting_year": year,
                        "reporting_month": month,
                        "value": value,
                        "created_at": at,
                        "created_by": actor_id,
                        "updated_at": at,
                        "updated_by": actor_id,
                    }
                    for (category_id, month), value in upserts.items()
                ]
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    constraint=MONTHLY_VALUE_IDENTITY_CONSTRAINT,
                    set_={
                        "value": statement.excluded.value,
                        "updated_at": statement.excluded.updated_at,
                        "updated_by": statement.excluded.updated_by,
                    },
                )
            )
        if deletes:
            self._session.execute(
                delete(v).where(
                    v.reporting_year == year,
                    tuple_(v.category_id, v.reporting_month).in_(list(deletes)),
                )
            )

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None:
        record_changes(
            self._session,
            actor_id=actor_id,
            change_set_id=change_set_id,
            occurred_at=at,
            changes=changes,
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
