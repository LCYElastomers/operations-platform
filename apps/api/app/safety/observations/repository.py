"""Database access for Safety Observations."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Select, delete, extract, func, insert, select, update
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.safety.observations.models import Observation, ObservationCategory


@dataclass(frozen=True)
class CategoryDefinition:
    id: int
    code: str
    name: str
    active: bool


@dataclass(frozen=True)
class ObservationValues:
    """The user-entered fields of an observation."""

    observed_on: dt.date
    outcome: str
    kind: str
    category_id: int
    area_location: str | None
    description: str | None
    corrective_action: str | None


@dataclass(frozen=True)
class ObservationRecord:
    id: int
    values: ObservationValues
    category_code: str
    category_name: str
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


@dataclass(frozen=True)
class ObservationFilter:
    observed_from: dt.date | None = None
    # Inclusive.
    observed_to: dt.date | None = None
    outcome: str | None = None
    kind: str | None = None
    category_id: int | None = None


@dataclass(frozen=True)
class CountRow:
    """Number of observations sharing a month, category, outcome, and kind."""

    month: int
    category_id: int
    outcome: str
    kind: str
    count: int


class ObservationRepository(Protocol):
    def categories(self) -> list[CategoryDefinition]:
        """All categories (active and inactive), in display order."""
        ...

    def search(
        self, criteria: ObservationFilter, *, limit: int, offset: int
    ) -> tuple[list[ObservationRecord], int]:
        """One page of matching observations, newest first, and the total match count."""
        ...

    def get(self, observation_id: int, *, for_update: bool = False) -> ObservationRecord | None: ...

    def insert(self, values: ObservationValues, *, actor_id: str, at: dt.datetime) -> int: ...

    def update(
        self, observation_id: int, values: ObservationValues, *, actor_id: str, at: dt.datetime
    ) -> None: ...

    def delete(self, observation_id: int) -> None: ...

    def counts(self, criteria: ObservationFilter) -> list[CountRow]: ...

    def years_with_observations(self) -> list[int]: ...

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


def _filtered(statement: Select[Any], criteria: ObservationFilter) -> Select[Any]:
    o = Observation
    if criteria.observed_from is not None:
        statement = statement.where(o.observed_on >= criteria.observed_from)
    if criteria.observed_to is not None:
        statement = statement.where(o.observed_on <= criteria.observed_to)
    if criteria.outcome is not None:
        statement = statement.where(o.outcome == criteria.outcome)
    if criteria.kind is not None:
        statement = statement.where(o.kind == criteria.kind)
    if criteria.category_id is not None:
        statement = statement.where(o.category_id == criteria.category_id)
    return statement


class DatabaseObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def categories(self) -> list[CategoryDefinition]:
        c = ObservationCategory
        rows = self._session.execute(
            select(c.id, c.code, c.name, c.active).order_by(c.display_order, c.id)
        ).all()
        return [
            CategoryDefinition(id=row.id, code=row.code, name=row.name, active=row.active)
            for row in rows
        ]

    def _records(self) -> Select[Any]:
        c = ObservationCategory
        # populate_existing: always return the stored row, never a stale session copy.
        return (
            select(Observation, c.code, c.name)
            .join(c, c.id == Observation.category_id)
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _record(observation: Observation, code: str, name: str) -> ObservationRecord:
        return ObservationRecord(
            id=observation.id,
            values=ObservationValues(
                observed_on=observation.observed_on,
                outcome=observation.outcome,
                kind=observation.kind,
                category_id=observation.category_id,
                area_location=observation.area_location,
                description=observation.description,
                corrective_action=observation.corrective_action,
            ),
            category_code=code,
            category_name=name,
            created_at=observation.created_at,
            created_by=observation.created_by,
            updated_at=observation.updated_at,
            updated_by=observation.updated_by,
        )

    def search(
        self, criteria: ObservationFilter, *, limit: int, offset: int
    ) -> tuple[list[ObservationRecord], int]:
        o = Observation
        total = self._session.scalar(_filtered(select(func.count()).select_from(o), criteria))
        rows = self._session.execute(
            _filtered(self._records(), criteria)
            .order_by(o.observed_on.desc(), o.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [self._record(*row) for row in rows], total or 0

    def get(self, observation_id: int, *, for_update: bool = False) -> ObservationRecord | None:
        statement = self._records().where(Observation.id == observation_id)
        if for_update:
            statement = statement.with_for_update(of=Observation)
        row = self._session.execute(statement).one_or_none()
        return None if row is None else self._record(*row)

    def insert(self, values: ObservationValues, *, actor_id: str, at: dt.datetime) -> int:
        observation_id = self._session.scalar(
            insert(Observation)
            .values(
                **vars(values),
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
            .returning(Observation.id)
        )
        assert observation_id is not None  # noqa: S101 - INSERT ... RETURNING yields the key
        return observation_id

    def update(
        self, observation_id: int, values: ObservationValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self._session.execute(
            update(Observation)
            .where(Observation.id == observation_id)
            .values(**vars(values), updated_at=at, updated_by=actor_id)
            .execution_options(synchronize_session=False)
        )

    def delete(self, observation_id: int) -> None:
        self._session.execute(
            delete(Observation)
            .where(Observation.id == observation_id)
            .execution_options(synchronize_session=False)
        )

    def counts(self, criteria: ObservationFilter) -> list[CountRow]:
        o = Observation
        month = extract("month", o.observed_on).label("month")
        rows = self._session.execute(
            _filtered(
                select(month, o.category_id, o.outcome, o.kind, func.count().label("count")),
                criteria,
            ).group_by(month, o.category_id, o.outcome, o.kind)
        ).all()
        return [
            CountRow(
                month=int(row.month),
                category_id=row.category_id,
                outcome=row.outcome,
                kind=row.kind,
                count=row.count,
            )
            for row in rows
        ]

    def years_with_observations(self) -> list[int]:
        year = extract("year", Observation.observed_on)
        years = self._session.scalars(select(year).distinct().order_by(year)).all()
        return [int(value) for value in years]

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
