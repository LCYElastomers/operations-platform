"""Access to moisture records.

Both read implementations return the same domain records, so the HTTP contract
is identical whether data comes from the development fixture or PostgreSQL.
"""

import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Protocol

from fastapi import Depends
from sqlalchemy import ColumnElement, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.ingestion.models import IngestionBatch
from app.quality.moisture import service
from app.quality.moisture.models import SOURCE_IDENTITY_CONSTRAINT, FinishingMeasurement
from app.quality.moisture.schemas import (
    DataSourceInfo,
    DateRange,
    MoistureFilterParams,
    MoistureRecord,
)
from app.quality.moisture.source import (
    DATABASE_DATA_SOURCE,
    FIXTURE_DATA_SOURCE,
    load_fixture_records,
)


@dataclass(frozen=True)
class FilterOptions:
    products: list[str]
    locations: list[str]
    date_range: DateRange


class MoistureRepository(Protocol):
    data_source: DataSourceInfo

    def recent(self, filters: MoistureFilterParams, limit: int) -> tuple[list[MoistureRecord], int]:
        """Newest matching records first, and the total number of matches."""
        ...

    def matching(self, filters: MoistureFilterParams) -> list[MoistureRecord]:
        """All matching records, oldest first."""
        ...

    def filter_options(self) -> FilterOptions: ...


class FixtureMoistureRepository:
    data_source = FIXTURE_DATA_SOURCE

    def __init__(self, records: Sequence[MoistureRecord]) -> None:
        self._records = records

    def recent(self, filters: MoistureFilterParams, limit: int) -> tuple[list[MoistureRecord], int]:
        matching = service.filter_records(self._records, filters)
        return service.newest_first(matching, limit), len(matching)

    def matching(self, filters: MoistureFilterParams) -> list[MoistureRecord]:
        return service.filter_records(self._records, filters)

    def filter_options(self) -> FilterOptions:
        return FilterOptions(
            products=service.distinct_values(record.product for record in self._records),
            locations=service.distinct_values(record.location for record in self._records),
            date_range=service.date_range(self._records),
        )


def _as_float(value: Decimal | None) -> float | None:
    # NUMERIC values were stored from the source's shortest round-trip text,
    # so converting back yields the same double the source provided.
    return None if value is None else float(value)


def _to_record(row: FinishingMeasurement) -> MoistureRecord:
    return MoistureRecord(
        date=row.source_date,
        campaign_no=row.campaign_no,
        lot=row.lot,
        location=row.location,
        product=row.product,
        avg_moisture=_as_float(row.avg_moisture),
        avg_color=_as_float(row.avg_color),
        avg_combined_bd=_as_float(row.avg_combined_bd),
    )


def _conditions(filters: MoistureFilterParams) -> list[ColumnElement[bool]]:
    m = FinishingMeasurement
    # Only current versions; superseded rows are kept for history.
    conditions: list[ColumnElement[bool]] = [m.superseded_at.is_(None)]
    # Product and location match exactly; stored values are not normalized.
    if filters.product is not None:
        conditions.append(m.product == filters.product)
    if filters.location is not None:
        conditions.append(m.location == filters.location)
    if filters.start_date is not None:
        conditions.append(m.source_date >= filters.start_date)
    if filters.end_date is not None:
        conditions.append(m.source_date <= filters.end_date)
    if filters.search is not None:
        conditions.append(
            or_(
                m.lot.icontains(filters.search, autoescape=True),
                m.campaign_no.icontains(filters.search, autoescape=True),
            )
        )
    return conditions


class DatabaseMoistureRepository:
    data_source = DATABASE_DATA_SOURCE

    def __init__(self, session: Session) -> None:
        self._session = session

    def recent(self, filters: MoistureFilterParams, limit: int) -> tuple[list[MoistureRecord], int]:
        m = FinishingMeasurement
        conditions = _conditions(filters)
        rows = self._session.scalars(
            select(m).where(*conditions).order_by(m.source_date.desc(), m.id.desc()).limit(limit)
        ).all()
        total = self._session.scalar(select(func.count()).select_from(m).where(*conditions))
        return [_to_record(row) for row in rows], total or 0

    def matching(self, filters: MoistureFilterParams) -> list[MoistureRecord]:
        m = FinishingMeasurement
        rows = self._session.scalars(
            select(m).where(*_conditions(filters)).order_by(m.source_date.asc(), m.id.asc())
        ).all()
        return [_to_record(row) for row in rows]

    def filter_options(self) -> FilterOptions:
        m = FinishingMeasurement
        current = m.superseded_at.is_(None)
        products = self._session.scalars(
            select(m.product).where(current, m.product.is_not(None)).distinct()
        ).all()
        locations = self._session.scalars(
            select(m.location).where(current, m.location.is_not(None)).distinct()
        ).all()
        earliest, latest = self._session.execute(
            select(func.min(m.source_date), func.max(m.source_date)).where(current)
        ).one()
        # Sort in Python so ordering matches the fixture regardless of DB collation.
        return FilterOptions(
            products=service.distinct_values(products),
            locations=service.distinct_values(locations),
            date_range=DateRange(min=earliest, max=latest),
        )


@dataclass(frozen=True)
class StoredVersion:
    id: int
    source_row_hash: str
    source_record_key: str | None
    is_current: bool


class FinishingMeasurementWriter:
    """Writes measurement versions. Never deletes; corrections supersede.

    The caller owns the transaction, so a batch split across several
    statements still commits or rolls back as a whole.
    """

    # PostgreSQL allows 65535 bind parameters per statement; 14 columns per row.
    chunk_size = 1000

    def __init__(self, session: Session) -> None:
        self._session = session

    def lock_source_system(self, source_system: str) -> None:
        """Serialize writes for one source system until the transaction ends."""
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"quality.finishing_measurements:{source_system}"},
        )

    def _versions(self, *conditions: ColumnElement[bool]) -> list[StoredVersion]:
        m = FinishingMeasurement
        rows = self._session.execute(
            select(m.id, m.source_row_hash, m.source_record_key, m.superseded_at).where(*conditions)
        ).all()
        return [
            StoredVersion(r.id, r.source_row_hash, r.source_record_key, r.superseded_at is None)
            for r in rows
        ]

    def versions_by_hash(
        self, source_system: str, hashes: Sequence[str]
    ) -> dict[str, StoredVersion]:
        if not hashes:
            return {}
        m = FinishingMeasurement
        versions = self._versions(m.source_system == source_system, m.source_row_hash.in_(hashes))
        return {v.source_row_hash: v for v in versions}

    def current_by_keys(self, source_system: str, keys: Sequence[str]) -> list[StoredVersion]:
        if not keys:
            return []
        m = FinishingMeasurement
        return self._versions(
            m.source_system == source_system,
            m.source_record_key.in_(keys),
            m.superseded_at.is_(None),
        )

    def current_in_window(
        self, source_system: str, start: dt.date, end: dt.date
    ) -> list[StoredVersion]:
        m = FinishingMeasurement
        return self._versions(
            m.source_system == source_system,
            m.source_date.between(start, end),
            m.superseded_at.is_(None),
        )

    def newer_key_versions_exist(
        self, source_system: str, keys: Sequence[str], extracted_at: dt.datetime
    ) -> bool:
        """Whether a current version of any key came from a later extraction."""
        if not keys:
            return False
        m, b = FinishingMeasurement, IngestionBatch
        return bool(
            self._session.scalar(
                select(
                    exists()
                    .where(m.ingestion_batch_id == b.id)
                    .where(
                        m.source_system == source_system,
                        m.source_record_key.in_(keys),
                        m.superseded_at.is_(None),
                        b.extracted_at > extracted_at,
                    )
                )
            )
        )

    def supersede(self, ids: Sequence[int], *, batch_pk: int, at: dt.datetime) -> int:
        if not ids:
            return 0
        m = FinishingMeasurement
        result = self._session.execute(
            update(m)
            .where(m.id.in_(ids), m.superseded_at.is_(None))
            .values(superseded_at=at, superseded_by_batch_id=batch_pk)
        )
        return result.rowcount

    def restore(self, ids: Sequence[int], *, batch_pk: int) -> int:
        """Make earlier versions current again; the restoring batch becomes their source."""
        if not ids:
            return 0
        m = FinishingMeasurement
        result = self._session.execute(
            update(m)
            .where(m.id.in_(ids), m.superseded_at.is_not(None))
            .values(superseded_at=None, superseded_by_batch_id=None, ingestion_batch_id=batch_pk)
        )
        return result.rowcount

    def insert_new(self, values: Sequence[Mapping[str, Any]]) -> int:
        """Insert rows and return how many were new."""
        inserted = 0
        for start in range(0, len(values), self.chunk_size):
            inserted += self._insert_chunk(values[start : start + self.chunk_size])
        return inserted

    def _insert_chunk(self, chunk: Sequence[Mapping[str, Any]]) -> int:
        statement = (
            insert(FinishingMeasurement)
            .values(list(chunk))
            .on_conflict_do_nothing(constraint=SOURCE_IDENTITY_CONSTRAINT)
            .returning(FinishingMeasurement.id)
        )
        return len(self._session.execute(statement).scalars().all())


def get_moisture_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[MoistureRepository]:
    """FastAPI dependency selecting the configured moisture data source."""
    if settings.moisture_data_source == "database":
        with get_sessionmaker()() as session:
            yield DatabaseMoistureRepository(session)
        return
    yield FixtureMoistureRepository(load_fixture_records())
