"""Read access to moisture records.

Both implementations return the same domain records, so the HTTP contract is
identical whether data comes from the development fixture or PostgreSQL.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.quality.moisture import service
from app.quality.moisture.models import FinishingMeasurement
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
    conditions: list[ColumnElement[bool]] = []
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
        products = self._session.scalars(
            select(m.product).where(m.product.is_not(None)).distinct()
        ).all()
        locations = self._session.scalars(
            select(m.location).where(m.location.is_not(None)).distinct()
        ).all()
        earliest, latest = self._session.execute(
            select(func.min(m.source_date), func.max(m.source_date))
        ).one()
        # Sort in Python so ordering matches the fixture regardless of DB collation.
        return FilterOptions(
            products=service.distinct_values(products),
            locations=service.distinct_values(locations),
            date_range=DateRange(min=earliest, max=latest),
        )


def get_moisture_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[MoistureRepository]:
    """FastAPI dependency selecting the configured moisture data source."""
    if settings.moisture_data_source == "database":
        with get_sessionmaker()() as session:
            yield DatabaseMoistureRepository(session)
        return
    yield FixtureMoistureRepository(load_fixture_records())
