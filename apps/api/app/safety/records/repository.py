"""Database access for Incident and Near Miss records."""

import datetime as dt
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, extract, func, insert, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.audit.models import AuditEvent
from app.audit.recorder import AuditChange, record_changes
from app.auth import people
from app.safety.models import Area, MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.records.models import NUMBER_INDEX, IncidentRecord

INCIDENTS_METRIC_SET = "incidents"
CLASSIFICATION_SECTION = "incident_classification"
TOTALS_SECTION = "incident_near_miss_totals"
# Monthly total category code for each event type.
TOTAL_CATEGORY = {"incident": "incident", "near_miss": "near_miss"}


class DuplicateIncidentNumberError(Exception):
    def __init__(self, number: str) -> None:
        super().__init__(number)
        self.number = number


@dataclass(frozen=True)
class RecordRow:
    record: IncidentRecord
    area_code: str | None
    area_name: str | None
    classification_code: str | None
    classification_name: str | None
    related_incident_number: str | None


@dataclass(frozen=True)
class Option:
    id: int
    code: str
    name: str
    active: bool


@dataclass(frozen=True)
class RecordFilter:
    year: int | None = None
    # January..through_month of ``year``.
    through_month: int | None = None
    month: int | None = None
    event_type: str | None = None
    area_id: int | None = None
    classification_category_id: int | None = None
    statuses: tuple[str, ...] = ("active",)
    search: str | None = None
    # Normalized number to match exactly, when the search text is a number.
    search_number: str | None = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RecordRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # Reading ---------------------------------------------------------------------

    def _select(self) -> Select[Any]:
        r, area, category = IncidentRecord, Area, MetricCategory
        related = aliased(IncidentRecord)
        return (
            select(
                r,
                area.code,
                area.name,
                category.code,
                category.name,
                related.incident_number,
            )
            .outerjoin(area, area.id == r.area_id)
            .outerjoin(category, category.id == r.classification_category_id)
            .outerjoin(related, related.id == r.related_incident_id)
        )

    @staticmethod
    def _row(row: Any) -> RecordRow:
        return RecordRow(row[0], row[1], row[2], row[3], row[4], row[5])

    def actor_names(self, actor_ids: Iterable[str | None]) -> dict[str, str]:
        return people.display_names(self._session, actor_ids)

    def get(self, record_id: int) -> RecordRow | None:
        row = self._session.execute(self._select().where(IncidentRecord.id == record_id)).first()
        return None if row is None else self._row(row)

    def lock(self, record_id: int) -> IncidentRecord | None:
        """The record, locked for update until the transaction ends."""
        return self._session.scalar(
            select(IncidentRecord).where(IncidentRecord.id == record_id).with_for_update()
        )

    def search(
        self, criteria: RecordFilter, *, limit: int, offset: int
    ) -> tuple[list[RecordRow], int]:
        r = IncidentRecord
        conditions = []
        if criteria.year is not None:
            start = dt.date(criteria.year, 1, 1)
            end = dt.date(criteria.year + 1, 1, 1)
            if criteria.month is not None:
                start = dt.date(criteria.year, criteria.month, 1)
                end = (
                    dt.date(criteria.year + 1, 1, 1)
                    if criteria.month == 12
                    else dt.date(criteria.year, criteria.month + 1, 1)
                )
            elif criteria.through_month is not None and criteria.through_month < 12:
                end = dt.date(criteria.year, criteria.through_month + 1, 1)
            conditions += [r.incident_date >= start, r.incident_date < end]
        if criteria.event_type is not None:
            conditions.append(r.event_type == criteria.event_type)
        if criteria.area_id is not None:
            conditions.append(r.area_id == criteria.area_id)
        if criteria.classification_category_id is not None:
            conditions.append(r.classification_category_id == criteria.classification_category_id)
        if criteria.statuses:
            conditions.append(r.status.in_(criteria.statuses))
        if criteria.search:
            pattern = f"%{_escape_like(criteria.search)}%"
            matches = [
                r.description.ilike(pattern, escape="\\"),
                r.incident_number.ilike(pattern, escape="\\"),
            ]
            if criteria.search_number is not None:
                matches.append(r.incident_number == criteria.search_number)
            conditions.append(or_(*matches))
        where = and_(true(), *conditions)
        total = self._session.scalar(select(func.count()).select_from(r).where(where)) or 0
        rows = self._session.execute(
            self._select().where(where).order_by(r.incident_date, r.id).limit(limit).offset(offset)
        ).all()
        return [self._row(row) for row in rows], total

    def documented_counts(self, year: int) -> dict[tuple[str, int], int]:
        """Active records per (event type, month) of ``year``."""
        r = IncidentRecord
        month = extract("month", r.incident_date)
        rows = self._session.execute(
            select(r.event_type, month, func.count())
            .where(
                r.status == "active",
                r.incident_date >= dt.date(year, 1, 1),
                r.incident_date < dt.date(year + 1, 1, 1),
            )
            .group_by(r.event_type, month)
        ).all()
        return {(event_type, int(m)): count for event_type, m, count in rows}

    def monthly_totals(self, year: int) -> dict[tuple[str, int], int]:
        """Stored monthly Incident and Near Miss totals of ``year``; absent when unreported."""
        v, c, s = MonthlyMetricValue, MetricCategory, MetricSection
        rows = self._session.execute(
            select(c.code, v.reporting_month, v.value)
            .join(c, c.id == v.category_id)
            .join(s, s.id == c.section_id)
            .where(
                s.metric_set == INCIDENTS_METRIC_SET,
                s.code == TOTALS_SECTION,
                c.code.in_(TOTAL_CATEGORY.values()),
                v.reporting_year == year,
            )
        ).all()
        by_code = {code: event_type for event_type, code in TOTAL_CATEGORY.items()}
        return {(by_code[code], month): value for code, month, value in rows}

    def areas(self) -> list[Option]:
        rows = self._session.execute(
            select(Area.id, Area.code, Area.name, Area.active).order_by(Area.display_order, Area.id)
        ).all()
        return [Option(*row) for row in rows]

    def classifications(self) -> list[Option]:
        c, s = MetricCategory, MetricSection
        rows = self._session.execute(
            select(c.id, c.code, c.name, c.active)
            .join(s, s.id == c.section_id)
            .where(s.metric_set == INCIDENTS_METRIC_SET, s.code == CLASSIFICATION_SECTION)
            .order_by(c.display_order, c.id)
        ).all()
        return [Option(*row) for row in rows]

    def source_reference_owner(self, reference: str) -> int | None:
        return self._session.scalar(
            select(IncidentRecord.id).where(IncidentRecord.source_reference == reference)
        )

    def number_owner(self, number: str) -> int | None:
        return self._session.scalar(
            select(IncidentRecord.id).where(IncidentRecord.incident_number == number)
        )

    def history(self, entity_type: str, entity_key: str) -> list[AuditEvent]:
        a = AuditEvent
        return list(
            self._session.scalars(
                select(a)
                .where(a.entity_type == entity_type, a.entity_key == entity_key)
                .order_by(a.occurred_at, a.id)
            )
        )

    # Writing ---------------------------------------------------------------------

    def insert(self, values: dict[str, Any], *, actor_id: str, at: dt.datetime) -> int:
        statement = (
            insert(IncidentRecord)
            .values(
                **values,
                version=1,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
            .returning(IncidentRecord.id)
        )
        try:
            with self._session.begin_nested():
                record_id = self._session.scalar(statement)
        except IntegrityError as error:
            self._raise_duplicate(error, values.get("incident_number"))
            raise
        assert record_id is not None  # noqa: S101 - INSERT ... RETURNING returns the id
        return record_id

    def update(
        self,
        record_id: int,
        values: dict[str, Any],
        *,
        version: int,
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        statement = (
            update(IncidentRecord)
            .where(IncidentRecord.id == record_id)
            .values(**values, version=version + 1, updated_at=at, updated_by=actor_id)
        )
        try:
            with self._session.begin_nested():
                self._session.execute(statement)
        except IntegrityError as error:
            self._raise_duplicate(error, values.get("incident_number"))
            raise
        self._session.expire_all()

    @staticmethod
    def _raise_duplicate(error: IntegrityError, number: str | None) -> None:
        if number is not None and NUMBER_INDEX in str(error.orig):
            raise DuplicateIncidentNumberError(number) from None

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
