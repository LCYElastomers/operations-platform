"""Database access for Cost of Quality: monthly inputs and Quality Cost records."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, delete, func, insert, or_, select, text, true, update
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.recorder import AuditChange, record_changes
from app.quality.cost.models import CostMonthlyFact, CostRecord, CostRecordReference
from app.safety.models import Area

IMPORT_LOCK_KEY = "quality.cost_monthly_facts"


@dataclass(frozen=True)
class Reference:
    type: str
    key: str
    label: str | None


@dataclass(frozen=True)
class RecordRow:
    record: CostRecord
    area_name: str | None
    references: tuple[Reference, ...] = ()


@dataclass(frozen=True)
class Option:
    id: int
    code: str
    name: str
    active: bool


@dataclass(frozen=True)
class RecordFilter:
    """Records matching every given criterion. Text criteria match case-insensitively."""

    date_from: dt.date | None = None
    date_to: dt.date | None = None
    area_id: int | None = None
    coq_classes: tuple[str, ...] = ()
    category_code: str | None = None
    product: str | None = None
    owner: str | None = None
    financial_statuses: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    search: str | None = None
    # A record id to match exactly, when the search text is a record number.
    search_id: int | None = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # Monthly inputs ------------------------------------------------------------

    def facts(self) -> dict[tuple[int, int], CostMonthlyFact]:
        rows = self.session.scalars(
            select(CostMonthlyFact).order_by(
                CostMonthlyFact.reporting_year, CostMonthlyFact.reporting_month
            )
        )
        return {(row.reporting_year, row.reporting_month): row for row in rows}

    def lock(self) -> None:
        """Serialize imports until the transaction ends."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": IMPORT_LOCK_KEY},
        )

    def insert(
        self, year: int, month: int, values: dict[str, Any], *, actor_id: str, at: dt.datetime
    ) -> None:
        self.session.execute(
            insert(CostMonthlyFact).values(
                reporting_year=year,
                reporting_month=month,
                **values,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
        )

    # Records: reading ----------------------------------------------------------

    def _select(self) -> Select[Any]:
        return select(CostRecord, Area.name).outerjoin(Area, Area.id == CostRecord.area_id)

    def _references(self, record_ids: Sequence[int]) -> dict[int, tuple[Reference, ...]]:
        if not record_ids:
            return {}
        ref = CostRecordReference
        rows = self.session.execute(
            select(ref.record_id, ref.target_type, ref.target_key, ref.label)
            .where(ref.record_id.in_(record_ids))
            .order_by(ref.record_id, ref.id)
        ).all()
        found: dict[int, list[Reference]] = {}
        for record_id, target_type, target_key, label in rows:
            found.setdefault(record_id, []).append(Reference(target_type, target_key, label))
        return {k: tuple(v) for k, v in found.items()}

    def _rows(self, rows: Sequence[Any]) -> list[RecordRow]:
        references = self._references([row[0].id for row in rows])
        return [RecordRow(row[0], row[1], references.get(row[0].id, ())) for row in rows]

    def get(self, record_id: int) -> RecordRow | None:
        row = self.session.execute(self._select().where(CostRecord.id == record_id)).first()
        return None if row is None else self._rows([row])[0]

    def lock_record(self, record_id: int) -> CostRecord | None:
        """The record, locked for update until the transaction ends."""
        return self.session.scalar(
            select(CostRecord).where(CostRecord.id == record_id).with_for_update()
        )

    def _where(self, criteria: RecordFilter) -> Any:
        r = CostRecord
        conditions: list[Any] = []
        if criteria.date_from is not None:
            conditions.append(r.record_date >= criteria.date_from)
        if criteria.date_to is not None:
            conditions.append(r.record_date <= criteria.date_to)
        if criteria.area_id is not None:
            conditions.append(r.area_id == criteria.area_id)
        if criteria.coq_classes:
            conditions.append(r.coq_class.in_(criteria.coq_classes))
        if criteria.category_code is not None:
            conditions.append(r.category_code == criteria.category_code)
        if criteria.product is not None:
            conditions.append(func.lower(r.product) == criteria.product.lower())
        if criteria.owner is not None:
            conditions.append(func.lower(r.owner) == criteria.owner.lower())
        if criteria.financial_statuses:
            conditions.append(r.financial_status.in_(criteria.financial_statuses))
        if criteria.statuses:
            conditions.append(r.status.in_(criteria.statuses))
        if criteria.search:
            pattern = f"%{_escape_like(criteria.search)}%"
            matches = [
                column.ilike(pattern, escape="\\")
                for column in (
                    r.title,
                    r.description,
                    r.product,
                    r.campaign,
                    r.lot,
                    r.owner,
                    r.counterparty,
                    r.notes,
                )
            ]
            if criteria.search_id is not None:
                matches.append(r.id == criteria.search_id)
            conditions.append(or_(*matches))
        return and_(true(), *conditions)

    def search(
        self, criteria: RecordFilter, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[RecordRow], int]:
        """Matching records, newest first, and how many match in all."""
        where = self._where(criteria)
        count = self.session.scalar(select(func.count()).select_from(CostRecord).where(where))
        statement = (
            self._select()
            .where(where)
            .order_by(CostRecord.record_date.desc(), CostRecord.id.desc())
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self._rows(self.session.execute(statement).all()), count or 0

    def record_years(self) -> list[int]:
        year = func.extract("year", CostRecord.record_date)
        return sorted((int(y) for y in self.session.scalars(select(year).distinct())), reverse=True)

    def areas(self) -> list[Option]:
        rows = self.session.execute(
            select(Area.id, Area.code, Area.name, Area.active).order_by(Area.display_order, Area.id)
        ).all()
        return [Option(*row) for row in rows]

    def distinct_values(self, column: str) -> list[str]:
        """Values used on records for ``product`` or ``owner``, alphabetical."""
        attribute = {"product": CostRecord.product, "owner": CostRecord.owner}[column]
        return sorted(
            self.session.scalars(select(attribute).where(attribute.is_not(None)).distinct()),
            key=str.lower,
        )

    def by_source_key(self) -> dict[str, CostRecord]:
        rows = self.session.scalars(select(CostRecord).where(CostRecord.source_key.is_not(None)))
        return {row.source_key: row for row in rows if row.source_key is not None}

    def history(self, entity_type: str, entity_key: str) -> list[AuditEvent]:
        a = AuditEvent
        return list(
            self.session.scalars(
                select(a)
                .where(a.entity_type == entity_type, a.entity_key == entity_key)
                .order_by(a.occurred_at, a.id)
            )
        )

    # Records: writing ----------------------------------------------------------

    def insert_record(self, values: dict[str, Any], *, actor_id: str, at: dt.datetime) -> int:
        record_id = self.session.scalar(
            insert(CostRecord)
            .values(
                **values,
                version=1,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
            .returning(CostRecord.id)
        )
        assert record_id is not None  # noqa: S101 - INSERT ... RETURNING returns the id
        return record_id

    def update_record(
        self,
        record_id: int,
        values: dict[str, Any],
        *,
        version: int,
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        self.session.execute(
            update(CostRecord)
            .where(CostRecord.id == record_id)
            .values(**values, version=version + 1, updated_at=at, updated_by=actor_id)
        )
        self.session.expire_all()

    def replace_references(
        self,
        record_id: int,
        references: Sequence[Reference],
        *,
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        self.session.execute(
            delete(CostRecordReference).where(CostRecordReference.record_id == record_id)
        )
        if references:
            self.session.execute(
                insert(CostRecordReference),
                [
                    {
                        "record_id": record_id,
                        "target_type": r.type,
                        "target_key": r.key,
                        "label": r.label,
                        "created_at": at,
                        "created_by": actor_id,
                    }
                    for r in references
                ],
            )

    def references_of(self, record_id: int) -> tuple[Reference, ...]:
        return self._references([record_id]).get(record_id, ())

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
