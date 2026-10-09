"""Database access for Corrective Action Reports."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, delete, func, insert, or_, select, text, true, update
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.recorder import AuditChange, record_changes
from app.quality.car.models import Car, CarAction, CarApproval, CarReference, CarWhyStep
from app.quality.cost.repository import CostRepository, RecordRow

NUMBER_LOCK_KEY = "quality.cars.number"
IMPORT_LOCK_KEY = "quality.cars.import"


@dataclass(frozen=True)
class Reference:
    type: str
    key: str
    label: str | None


@dataclass(frozen=True)
class WhyStep:
    what: str | None
    why: str | None
    root_cause: str | None
    countermeasure: str | None
    who: str | None
    target_date: dt.date | None


@dataclass(frozen=True)
class Approval:
    function_code: str
    name: str
    approved_on: dt.date | None


@dataclass(frozen=True)
class CarRow:
    car: Car
    actions: tuple[CarAction, ...]
    why_steps: tuple[CarWhyStep, ...] = ()
    approvals: tuple[CarApproval, ...] = ()
    references: tuple[Reference, ...] = ()
    quality_cost: RecordRow | None = None


@dataclass(frozen=True)
class CarFilter:
    """Reports matching every given criterion. Text criteria match case-insensitively."""

    date_from: dt.date | None = None
    date_to: dt.date | None = None
    # "open", "closed" and "not_recorded".
    statuses: tuple[str, ...] = ()
    departments: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    root_causes: tuple[str, ...] = ()
    # "effective", "not_effective" and "not_recorded".
    effectiveness: tuple[str, ...] = ()
    assigned_to: str | None = None
    # Not closed and due before this date.
    past_due_on: dt.date | None = None
    repeat: bool | None = None
    search: str | None = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _with_not_recorded(column: Any, values: tuple[str, ...]) -> Any:
    codes = [v for v in values if v != "not_recorded"]
    matches = [column.in_(codes)] if codes else []
    if "not_recorded" in values:
        matches.append(column.is_(None))
    return or_(*matches)


class CarRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # Reading -------------------------------------------------------------------

    def _actions(self, car_ids: Sequence[int]) -> dict[int, tuple[CarAction, ...]]:
        if not car_ids:
            return {}
        found: dict[int, list[CarAction]] = {}
        rows = self.session.scalars(
            select(CarAction)
            .where(CarAction.car_id.in_(car_ids))
            .order_by(CarAction.car_id, CarAction.position, CarAction.id)
        )
        for action in rows:
            found.setdefault(action.car_id, []).append(action)
        return {k: tuple(v) for k, v in found.items()}

    def actions_of(self, car_id: int) -> tuple[CarAction, ...]:
        return self._actions([car_id]).get(car_id, ())

    def get(self, car_id: int) -> CarRow | None:
        car = self.session.get(Car, car_id, populate_existing=True)
        if car is None:
            return None
        why = tuple(
            self.session.scalars(
                select(CarWhyStep).where(CarWhyStep.car_id == car_id).order_by(CarWhyStep.position)
            )
        )
        approvals = tuple(
            self.session.scalars(
                select(CarApproval).where(CarApproval.car_id == car_id).order_by(CarApproval.id)
            )
        )
        cost = (
            CostRepository(self.session).get(car.quality_cost_record_id)
            if car.quality_cost_record_id is not None
            else None
        )
        return CarRow(
            car=car,
            actions=self._actions([car_id]).get(car_id, ()),
            why_steps=why,
            approvals=approvals,
            references=self.references_of(car_id),
            quality_cost=cost,
        )

    def lock(self, car_id: int) -> Car | None:
        """The report, locked for update until the transaction ends."""
        return self.session.scalar(
            select(Car)
            .where(Car.id == car_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_action(self, car_id: int, action_id: int) -> CarAction | None:
        return self.session.scalar(
            select(CarAction)
            .where(CarAction.id == action_id, CarAction.car_id == car_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _where(self, criteria: CarFilter) -> Any:
        c = Car
        conditions: list[Any] = []
        if criteria.date_from is not None:
            conditions.append(c.request_date >= criteria.date_from)
        if criteria.date_to is not None:
            conditions.append(c.request_date <= criteria.date_to)
        if criteria.statuses:
            conditions.append(_with_not_recorded(c.status, criteria.statuses))
        if criteria.departments:
            conditions.append(_with_not_recorded(c.department_code, criteria.departments))
        if criteria.sources:
            conditions.append(_with_not_recorded(c.source_code, criteria.sources))
        if criteria.root_causes:
            conditions.append(_with_not_recorded(c.root_cause_code, criteria.root_causes))
        if criteria.effectiveness:
            conditions.append(_with_not_recorded(c.effectiveness_result, criteria.effectiveness))
        if criteria.assigned_to is not None:
            conditions.append(func.lower(c.assigned_to) == criteria.assigned_to.lower())
        if criteria.past_due_on is not None:
            conditions.append(
                and_(
                    c.status.is_distinct_from("closed"),
                    c.due_date.is_not(None),
                    c.due_date < criteria.past_due_on,
                )
            )
        if criteria.repeat is not None:
            conditions.append(
                c.previous_occurrence.is_(True)
                if criteria.repeat
                else c.previous_occurrence.is_not(True)
            )
        if criteria.search:
            pattern = f"%{_escape_like(criteria.search)}%"
            conditions.append(
                or_(
                    *(
                        column.ilike(pattern, escape="\\")
                        for column in (
                            c.car_number,
                            c.subject,
                            c.requested_by,
                            c.assigned_to,
                            c.nonconformity_description,
                            c.incident_type,
                            c.true_root_cause,
                            c.product,
                            c.lot,
                            c.work_order_number,
                        )
                    )
                )
            )
        return and_(true(), *conditions)

    def _select(self) -> Select[Any]:
        return select(Car)

    def search(
        self, criteria: CarFilter, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[CarRow], int]:
        """Matching reports, newest first, with their actions, and how many match in all."""
        where = self._where(criteria)
        count = self.session.scalar(select(func.count()).select_from(Car).where(where))
        statement = (
            self._select()
            .where(where)
            .order_by(Car.request_date.desc(), Car.car_number.desc())
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        cars = list(self.session.scalars(statement))
        actions = self._actions([c.id for c in cars])
        return [CarRow(car, actions.get(car.id, ())) for car in cars], count or 0

    def people(self) -> tuple[list[str], list[str]]:
        """(every name used on reports, the names reports are assigned to), alphabetical."""
        columns = (Car.requested_by, Car.assigned_to, Car.containment_owner, Car.reviewer)
        names: set[str] = set()
        for column in columns:
            names.update(self.session.scalars(select(column).where(column.is_not(None)).distinct()))
        names.update(
            self.session.scalars(
                select(CarAction.owner).where(CarAction.owner.is_not(None)).distinct()
            )
        )
        assignees = set(
            self.session.scalars(
                select(Car.assigned_to).where(Car.assigned_to.is_not(None)).distinct()
            )
        )
        return sorted(names, key=str.lower), sorted(assignees, key=str.lower)

    def numbers_for_year(self, prefix: str, year: int) -> list[str]:
        return list(
            self.session.scalars(
                select(Car.car_number).where(Car.car_number.like(f"{prefix}-{year}-%"))
            )
        )

    def all_numbers(self) -> set[str]:
        return set(self.session.scalars(select(Car.car_number)))

    def by_source_key(self) -> dict[str, Car]:
        rows = self.session.scalars(select(Car).where(Car.source_key.is_not(None)))
        return {row.source_key: row for row in rows if row.source_key is not None}

    def car_for_cost_record(self, record_id: int) -> Car | None:
        return self.session.scalar(select(Car).where(Car.quality_cost_record_id == record_id))

    def references_of(self, car_id: int) -> tuple[Reference, ...]:
        r = CarReference
        rows = self.session.execute(
            select(r.target_type, r.target_key, r.label).where(r.car_id == car_id).order_by(r.id)
        ).all()
        return tuple(Reference(*row) for row in rows)

    def history(self, entity_types: Sequence[str], car_key: str) -> list[AuditEvent]:
        """Audit events of a report and its actions (keys under ``car_key``), oldest first."""
        a = AuditEvent
        return list(
            self.session.scalars(
                select(a)
                .where(
                    a.entity_type.in_(entity_types),
                    or_(
                        a.entity_key == car_key,
                        a.entity_key.like(f"{_escape_like(car_key)}/%", escape="\\"),
                    ),
                )
                .order_by(a.occurred_at, a.id)
            )
        )

    # Writing -------------------------------------------------------------------

    def lock_numbers(self) -> None:
        """Serialize number assignment until the transaction ends."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": NUMBER_LOCK_KEY},
        )

    def lock_import(self) -> None:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": IMPORT_LOCK_KEY},
        )

    def insert_car(self, values: dict[str, Any], *, actor_id: str, at: dt.datetime) -> int:
        car_id = self.session.scalar(
            insert(Car)
            .values(
                **values,
                version=1,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
            .returning(Car.id)
        )
        assert car_id is not None  # noqa: S101 - INSERT ... RETURNING returns the id
        return car_id

    def update_car(
        self, car_id: int, values: dict[str, Any], *, version: int, actor_id: str, at: dt.datetime
    ) -> None:
        self.session.execute(
            update(Car)
            .where(Car.id == car_id)
            .values(**values, version=version + 1, updated_at=at, updated_by=actor_id)
        )
        self.session.expire_all()

    def touch_car(self, car_id: int, *, version: int, actor_id: str, at: dt.datetime) -> None:
        """A child-only change: bump the report's version and update stamp."""
        self.update_car(car_id, {}, version=version, actor_id=actor_id, at=at)

    def next_action_position(self, car_id: int) -> int:
        current = self.session.scalar(
            select(func.max(CarAction.position)).where(CarAction.car_id == car_id)
        )
        return (current or 0) + 1

    def insert_action(
        self, car_id: int, values: dict[str, Any], *, actor_id: str, at: dt.datetime
    ) -> int:
        action_id = self.session.scalar(
            insert(CarAction)
            .values(
                car_id=car_id,
                **values,
                version=1,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
            .returning(CarAction.id)
        )
        assert action_id is not None  # noqa: S101 - INSERT ... RETURNING returns the id
        return action_id

    def update_action(
        self,
        action_id: int,
        values: dict[str, Any],
        *,
        version: int,
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        self.session.execute(
            update(CarAction)
            .where(CarAction.id == action_id)
            .values(**values, version=version + 1, updated_at=at, updated_by=actor_id)
        )
        self.session.expire_all()

    def replace_why_steps(
        self, car_id: int, steps: Sequence[WhyStep], *, actor_id: str, at: dt.datetime
    ) -> None:
        self.session.execute(delete(CarWhyStep).where(CarWhyStep.car_id == car_id))
        if steps:
            self.session.execute(
                insert(CarWhyStep),
                [
                    {
                        "car_id": car_id,
                        "position": position,
                        "what": s.what,
                        "why": s.why,
                        "root_cause": s.root_cause,
                        "countermeasure": s.countermeasure,
                        "who": s.who,
                        "target_date": s.target_date,
                        "created_at": at,
                        "created_by": actor_id,
                    }
                    for position, s in enumerate(steps, start=1)
                ],
            )

    def replace_approvals(
        self, car_id: int, approvals: Sequence[Approval], *, actor_id: str, at: dt.datetime
    ) -> None:
        """Keep unchanged approvals (and who recorded them); replace the rest."""
        current = {
            a.function_code: a
            for a in self.session.scalars(select(CarApproval).where(CarApproval.car_id == car_id))
        }
        wanted = {a.function_code: a for a in approvals}
        for code, row in current.items():
            new = wanted.get(code)
            if new is None or (new.name, new.approved_on) != (row.name, row.approved_on):
                self.session.execute(delete(CarApproval).where(CarApproval.id == row.id))
        for code, new in wanted.items():
            row = current.get(code)
            if row is None or (new.name, new.approved_on) != (row.name, row.approved_on):
                self.session.execute(
                    insert(CarApproval).values(
                        car_id=car_id,
                        function_code=code,
                        name=new.name,
                        approved_on=new.approved_on,
                        created_at=at,
                        created_by=actor_id,
                    )
                )
        self.session.expire_all()

    def replace_references(
        self, car_id: int, references: Sequence[Reference], *, actor_id: str, at: dt.datetime
    ) -> None:
        self.session.execute(delete(CarReference).where(CarReference.car_id == car_id))
        if references:
            self.session.execute(
                insert(CarReference),
                [
                    {
                        "car_id": car_id,
                        "target_type": r.type,
                        "target_key": r.key,
                        "label": r.label,
                        "created_at": at,
                        "created_by": actor_id,
                    }
                    for r in references
                ],
            )

    def why_steps_of(self, car_id: int) -> tuple[WhyStep, ...]:
        rows = self.session.scalars(
            select(CarWhyStep).where(CarWhyStep.car_id == car_id).order_by(CarWhyStep.position)
        )
        return tuple(
            WhyStep(r.what, r.why, r.root_cause, r.countermeasure, r.who, r.target_date)
            for r in rows
        )

    def approvals_of(self, car_id: int) -> tuple[Approval, ...]:
        rows = self.session.scalars(
            select(CarApproval).where(CarApproval.car_id == car_id).order_by(CarApproval.id)
        )
        return tuple(Approval(r.function_code, r.name, r.approved_on) for r in rows)

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None:
        record_changes(
            self.session,
            actor_id=actor_id,
            change_set_id=change_set_id,
            occurred_at=at,
            changes=changes,
        )

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
