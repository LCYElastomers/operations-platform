"""PostgreSQL integration tests for annual Behavior counts (migration 0008).

Enabled by TEST_DATABASE_URL (see test_moisture_database.py). Every test runs in
a transaction that is rolled back; writes use a far-future year so they cannot
meet imported data.
"""

import datetime as dt
import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, func, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.safety.behavior import service
from app.safety.behavior.models import AnnualBehaviorCount, BehaviorCategory
from app.safety.behavior.repository import DatabaseBehaviorRepository
from app.safety.behavior.schemas import BehaviorChange

pytestmark = requires_postgres

API_ROOT = Path(service.__file__).resolve().parents[3]
YEAR = 2099
NOW = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.UTC)


def migration_0008() -> ModuleType:
    path = next((API_ROOT / "alembic" / "versions").glob("*-0008_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0008", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NonCommittingRepository(DatabaseBehaviorRepository):
    """Flushes instead of committing, so the test transaction can be rolled back."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.session = session

    def commit(self) -> None:
        self.session.flush()

    def rollback(self) -> None:
        pass


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        yield db
        db.close()
        transaction.rollback()


@pytest.fixture
def repository(session: Session) -> NonCommittingRepository:
    return NonCommittingRepository(session)


def ids(repository: DatabaseBehaviorRepository) -> dict[str, int]:
    return {c.code: c.id for c in repository.categories()}


def test_annual_table_has_no_month_and_one_row_per_category_year(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("annual_behavior_counts", "safety")}
    assert "reporting_year" in columns
    assert not any("month" in column for column in columns)
    uniques = inspector.get_unique_constraints("annual_behavior_counts", "safety")
    assert [(u["name"], u["column_names"]) for u in uniques] == [
        ("uq_annual_behavior_counts_category_year", ["category_id", "reporting_year"])
    ]


def test_all_24_categories_are_seeded_in_display_order(
    repository: DatabaseBehaviorRepository,
) -> None:
    expected = [(code, name) for code, name in migration_0008().BEHAVIOR_CATEGORIES]
    categories = repository.categories()
    assert [(c.code, c.name) for c in categories] == expected
    assert [c.display_order for c in categories] == list(range(1, 25))


def test_save_round_trip_with_explicit_zero_and_blank(
    repository: NonCommittingRepository, session: Session
) -> None:
    by_code = ids(repository)
    service.save_counts(
        repository,
        year=YEAR,
        changes=[
            BehaviorChange(category_id=by_code["eyes_on_path"], value=12, previous_value=None),
            BehaviorChange(category_id=by_code["housekeeping"], value=0, previous_value=None),
        ],
        actor_id="db-test",
        now=NOW,
    )
    assert repository.counts(YEAR) == {by_code["eyes_on_path"]: 12, by_code["housekeeping"]: 0}
    assert YEAR in repository.years_with_counts()

    service.save_counts(
        repository,
        year=YEAR,
        changes=[
            BehaviorChange(category_id=by_code["eyes_on_path"], value=13, previous_value=12),
            BehaviorChange(category_id=by_code["housekeeping"], value=None, previous_value=0),
        ],
        actor_id="db-test",
        now=NOW,
    )
    assert repository.counts(YEAR) == {by_code["eyes_on_path"]: 13}

    keys = session.scalars(
        select(AuditEvent.entity_key)
        .where(AuditEvent.entity_type == service.AUDIT_ENTITY_TYPE)
        .where(AuditEvent.entity_key.like(f"%/{YEAR}"))
        .order_by(AuditEvent.id)
    ).all()
    assert keys == [
        f"incidents/behavior/eyes_on_path/{YEAR}",
        f"incidents/behavior/housekeeping/{YEAR}",
        f"incidents/behavior/eyes_on_path/{YEAR}",
        f"incidents/behavior/housekeeping/{YEAR}",
    ]


@pytest.mark.parametrize(
    ("year", "value"),
    [(YEAR, -1), (1999, 1), (2101, 1)],
)
def test_constraints_reject_negative_counts_and_out_of_range_years(
    session: Session, year: int, value: int
) -> None:
    category_id = session.scalar(select(func.min(BehaviorCategory.id)))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            insert(AnnualBehaviorCount).values(
                category_id=category_id,
                reporting_year=year,
                value=value,
                created_at=NOW,
                created_by="db-test",
                updated_at=NOW,
                updated_by="db-test",
            )
        )


def test_a_category_with_counts_cannot_be_deleted(
    repository: NonCommittingRepository, session: Session
) -> None:
    category_id = ids(repository)["ppe_eye"]
    service.save_counts(
        repository,
        year=YEAR,
        changes=[BehaviorChange(category_id=category_id, value=1, previous_value=None)],
        actor_id="db-test",
        now=NOW,
    )
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            text("DELETE FROM safety.behavior_categories WHERE id = :id"), {"id": category_id}
        )


def test_downgrade_guard_refuses_while_counts_exist(
    repository: NonCommittingRepository, session: Session
) -> None:
    category_id = ids(repository)["ppe_eye"]
    service.save_counts(
        repository,
        year=YEAR,
        changes=[BehaviorChange(category_id=category_id, value=1, previous_value=None)],
        actor_id="db-test",
        now=NOW,
    )
    with pytest.raises(DBAPIError, match="Cannot downgrade"), session.begin_nested():
        session.execute(text(migration_0008().DOWNGRADE_GUARD))
