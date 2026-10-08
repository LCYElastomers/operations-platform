"""Database access for annual Behavior counts."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.safety.behavior.models import (
    COUNT_IDENTITY_CONSTRAINT,
    AnnualBehaviorCount,
    BehaviorCategory,
)


@dataclass(frozen=True)
class BehaviorCategoryDefinition:
    id: int
    code: str
    name: str
    display_order: int


# category_id -> stored annual count
StoredCounts = dict[int, int]


class BehaviorRepository(Protocol):
    def categories(self) -> list[BehaviorCategoryDefinition]:
        """Active Behavior categories in display order."""
        ...

    def counts(self, year: int) -> StoredCounts: ...

    def years_with_counts(self) -> list[int]: ...

    def lock_year(self, year: int) -> None:
        """Serialize saves for one year until the transaction ends."""
        ...

    def write(
        self,
        *,
        year: int,
        upserts: dict[int, int],
        deletes: Sequence[int],
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


class DatabaseBehaviorRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def categories(self) -> list[BehaviorCategoryDefinition]:
        c = BehaviorCategory
        rows = self._session.execute(
            select(c.id, c.code, c.name, c.display_order)
            .where(c.active.is_(True))
            .order_by(c.display_order, c.id)
        ).all()
        return [
            BehaviorCategoryDefinition(
                id=row.id, code=row.code, name=row.name, display_order=row.display_order
            )
            for row in rows
        ]

    def counts(self, year: int) -> StoredCounts:
        v = AnnualBehaviorCount
        rows = self._session.execute(
            select(v.category_id, v.value).where(v.reporting_year == year)
        ).all()
        return {row.category_id: row.value for row in rows}

    def years_with_counts(self) -> list[int]:
        v = AnnualBehaviorCount
        return list(
            self._session.scalars(
                select(v.reporting_year).distinct().order_by(v.reporting_year)
            ).all()
        )

    def lock_year(self, year: int) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"safety.annual_behavior_counts:{year}"},
        )

    def write(
        self,
        *,
        year: int,
        upserts: dict[int, int],
        deletes: Sequence[int],
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        v = AnnualBehaviorCount
        if upserts:
            statement = insert(v).values(
                [
                    {
                        "category_id": category_id,
                        "reporting_year": year,
                        "value": value,
                        "created_at": at,
                        "created_by": actor_id,
                        "updated_at": at,
                        "updated_by": actor_id,
                    }
                    for category_id, value in upserts.items()
                ]
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    constraint=COUNT_IDENTITY_CONSTRAINT,
                    set_={
                        "value": statement.excluded.value,
                        "updated_at": statement.excluded.updated_at,
                        "updated_by": statement.excluded.updated_by,
                    },
                )
            )
        if deletes:
            self._session.execute(
                delete(v).where(v.reporting_year == year, v.category_id.in_(list(deletes)))
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
