"""Database access for Safety Performance."""

import datetime as dt
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import delete, insert, select, text, tuple_, update
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.performance.calculations import (
    INCIDENT_CATEGORIES,
    INCIDENTS,
    LEGACY_CATEGORIES,
    PERFORMANCE_LEGACY,
    Period,
)
from app.safety.performance.models import PerformanceAnnualLegacy, PerformanceHours


@dataclass(frozen=True)
class HoursValues:
    total_hours: Decimal
    hourly_hours: Decimal | None
    salary_hours: Decimal | None
    month_closed: bool


@dataclass(frozen=True)
class HoursRecord:
    year: int
    month: int
    values: HoursValues
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


@dataclass(frozen=True)
class AnnualValues:
    recordables: int
    total_hours: Decimal
    source: str


@dataclass(frozen=True)
class AnnualRecord:
    year: int
    values: AnnualValues


# Stored monthly counts by period, keyed by the names in INCIDENT_CATEGORIES or
# LEGACY_CATEGORIES. A name is absent when the month has no stored value.
StoredCounts = dict[Period, dict[str, int]]


class PerformanceRepository(Protocol):
    def hours(self) -> dict[Period, HoursRecord]:
        """Every month with reported hours."""
        ...

    def get_hours(self, year: int, month: int) -> HoursRecord | None: ...

    def lock_month(self, year: int, month: int) -> None:
        """Serialize writers of one month until the transaction ends."""
        ...

    def insert_hours(
        self, year: int, month: int, values: HoursValues, *, actor_id: str, at: dt.datetime
    ) -> None: ...

    def update_hours(
        self, year: int, month: int, values: HoursValues, *, actor_id: str, at: dt.datetime
    ) -> None: ...

    def delete_hours(self, year: int, month: int) -> None: ...

    def annual_legacy(self) -> dict[int, AnnualRecord]: ...

    def lock_annual(self, year: int) -> None: ...

    def insert_annual(
        self, year: int, values: AnnualValues, *, actor_id: str, at: dt.datetime
    ) -> None: ...

    def counts(self, years: Collection[int]) -> tuple[StoredCounts, StoredCounts]:
        """Stored Incident & Near Miss and legacy workbook counts for ``years``."""
        ...

    def record_audit(
        self,
        changes: Sequence[AuditChange],
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def _hours_record(row: PerformanceHours) -> HoursRecord:
    return HoursRecord(
        year=row.reporting_year,
        month=row.reporting_month,
        values=HoursValues(
            total_hours=row.total_hours,
            hourly_hours=row.hourly_hours,
            salary_hours=row.salary_hours,
            month_closed=row.month_closed,
        ),
        created_at=row.created_at,
        created_by=row.created_by,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def _hours_columns(values: HoursValues) -> dict[str, object]:
    return {
        "total_hours": values.total_hours,
        "hourly_hours": values.hourly_hours,
        "salary_hours": values.salary_hours,
        "month_closed": values.month_closed,
    }


class DatabasePerformanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def hours(self) -> dict[Period, HoursRecord]:
        rows = self._session.scalars(select(PerformanceHours))
        return {(r.reporting_year, r.reporting_month): _hours_record(r) for r in rows}

    def get_hours(self, year: int, month: int) -> HoursRecord | None:
        row = self._session.scalars(
            select(PerformanceHours).where(
                PerformanceHours.reporting_year == year,
                PerformanceHours.reporting_month == month,
            )
        ).one_or_none()
        return _hours_record(row) if row is not None else None

    def lock_month(self, year: int, month: int) -> None:
        # The row may not exist yet, so lock its identity rather than the row.
        self._advisory_lock(f"safety.performance_hours/{year:04d}-{month:02d}")

    def lock_annual(self, year: int) -> None:
        self._advisory_lock(f"safety.performance_annual_legacy/{year:04d}")

    def _advisory_lock(self, key: str) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )

    def insert_hours(
        self, year: int, month: int, values: HoursValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self._session.execute(
            insert(PerformanceHours).values(
                reporting_year=year,
                reporting_month=month,
                **_hours_columns(values),
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
        )

    def update_hours(
        self, year: int, month: int, values: HoursValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self._session.execute(
            update(PerformanceHours)
            .where(
                PerformanceHours.reporting_year == year,
                PerformanceHours.reporting_month == month,
            )
            .values(**_hours_columns(values), updated_at=at, updated_by=actor_id)
        )

    def delete_hours(self, year: int, month: int) -> None:
        self._session.execute(
            delete(PerformanceHours).where(
                PerformanceHours.reporting_year == year,
                PerformanceHours.reporting_month == month,
            )
        )

    def annual_legacy(self) -> dict[int, AnnualRecord]:
        rows = self._session.scalars(select(PerformanceAnnualLegacy))
        return {
            r.reporting_year: AnnualRecord(
                year=r.reporting_year,
                values=AnnualValues(
                    recordables=r.recordables, total_hours=r.total_hours, source=r.source
                ),
            )
            for r in rows
        }

    def insert_annual(
        self, year: int, values: AnnualValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self._session.execute(
            insert(PerformanceAnnualLegacy).values(
                reporting_year=year,
                recordables=values.recordables,
                total_hours=values.total_hours,
                source=values.source,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
        )

    def counts(self, years: Collection[int]) -> tuple[StoredCounts, StoredCounts]:
        return (
            self._metric_counts(INCIDENTS, INCIDENT_CATEGORIES, years),
            self._metric_counts(PERFORMANCE_LEGACY, LEGACY_CATEGORIES, years),
        )

    def _metric_counts(
        self, metric_set: str, names: dict[str, tuple[str, str]], years: Collection[int]
    ) -> StoredCounts:
        if not years:
            return {}
        name_of = {key: name for name, key in names.items()}
        rows = self._session.execute(
            select(
                MetricSection.code,
                MetricCategory.code,
                MonthlyMetricValue.reporting_year,
                MonthlyMetricValue.reporting_month,
                MonthlyMetricValue.value,
            )
            .join(MetricCategory, MetricCategory.section_id == MetricSection.id)
            .join(MonthlyMetricValue, MonthlyMetricValue.category_id == MetricCategory.id)
            .where(
                MetricSection.metric_set == metric_set,
                tuple_(MetricSection.code, MetricCategory.code).in_(list(name_of)),
                MonthlyMetricValue.reporting_year.in_(list(years)),
            )
        )
        stored: StoredCounts = {}
        for section, category, year, month, value in rows:
            stored.setdefault((year, month), {})[name_of[(section, category)]] = value
        return stored

    def record_audit(
        self,
        changes: Sequence[AuditChange],
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
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
