"""PostgreSQL integration tests for quality.finishing_measurements.

Run through tests/run_disposable_database.py, which creates a throwaway
database, points TEST_DATABASE_URL at it and drops it afterwards. With
TEST_DATABASE_MODE=shared the populated shared test database is used without
migrating it (see postgres_support.py).

As in production, the `core` schema must already exist and the role needs
USAGE and CREATE on it (and on `quality`, or CREATE on the database).
"""

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from postgres_support import (
    TEST_DATABASE_URL,
    alembic_config,
    current_revision,
    requires_postgres,
)
from principals import as_user
from sqlalchemy import Engine, func, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.authorization import get_user_principal
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.base import ALEMBIC_VERSION_SCHEMA, ALEMBIC_VERSION_TABLE, MANAGED_SCHEMAS
from app.main import create_app
from app.models import Base, IngestionBatch
from app.quality.moisture import repository as repository_module
from app.quality.moisture.ingestion import compute_source_row_hash, insert_source_rows
from app.quality.moisture.models import FinishingMeasurement
from app.quality.moisture.repository import (
    DatabaseMoistureRepository,
    FixtureMoistureRepository,
    get_moisture_repository,
)
from app.quality.moisture.schemas import MoistureFilterParams
from app.quality.moisture.source import record_from_source_row

pytestmark = requires_postgres

SYNCED_AT = dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.UTC)
SOURCE = "access-test"
BASE = "/api/v1/quality/moisture"
HEAD = "0013"


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after each test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        yield db
        db.close()
        transaction.rollback()


def source_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "DATE": "2026-09-01",
        "CAMPNO": "26101",
        "LOT": "A260901-01",
        "Location": "Silo 1",
        "PRODUCT": "PRD-A",
        "AvgOfMOISTURE": 0.4,
        "AvgOfCOLOR": 40.0,
        "AvgOfCombined_BD": 0.7,
    }
    row.update(overrides)
    return row


def store(db: Session, *rows: dict[str, Any], source_system: str = SOURCE) -> int:
    return insert_source_rows(db, rows, source_system=source_system, synced_at=SYNCED_AT)


def stored_rows(db: Session) -> list[FinishingMeasurement]:
    return list(db.scalars(select(FinishingMeasurement).order_by(FinishingMeasurement.id)))


SAMPLE_ROWS = [
    source_row(DATE="2026-09-01", LOT="A260901-01", CAMPNO="26101", PRODUCT="PRD-A",
               Location="Silo 1", AvgOfMOISTURE=0.0),
    source_row(DATE="2026-09-02", LOT="B260902-02", CAMPNO="26201", PRODUCT="PRD-B",
               Location="SILO 1", AvgOfMOISTURE=None),
    source_row(DATE="2026-09-03", LOT="A260903-03", CAMPNO="26102", PRODUCT="PRD-A",
               Location="Railcar", AvgOfMOISTURE=0.5),
    source_row(DATE="2026-09-04", LOT=None, CAMPNO="26202", PRODUCT="PRD-B",
               Location="Silo 2", AvgOfMOISTURE=0.6, AvgOfCOLOR=None),
]  # fmt: skip


def lots(records: list[Any]) -> list[str | None]:
    return [record.lot for record in records]


# Migrations -----------------------------------------------------------------------


def test_alembic_history_is_linear() -> None:
    script = ScriptDirectory.from_config(alembic_config())

    assert script.get_heads() == [HEAD]
    assert script.get_revision("0012").down_revision == "0011"
    assert script.get_revision("0011").down_revision == "0010"
    assert script.get_revision("0010").down_revision == "0009"
    assert script.get_revision("0009").down_revision == "0008"
    assert script.get_revision("0008").down_revision == "0007"
    assert script.get_revision("0007").down_revision == "0006"
    assert script.get_revision("0006").down_revision == "0005"
    assert script.get_revision("0005").down_revision == "0004"
    assert script.get_revision("0004").down_revision == "0003"
    assert script.get_revision("0003").down_revision == "0002"
    assert script.get_revision("0002").down_revision == "0001"
    assert script.get_revision("0001").down_revision is None


def test_upgrade_head_creates_tables(engine: Engine) -> None:
    inspector = inspect(engine)

    assert inspector.has_table("finishing_measurements", schema="quality")
    assert inspector.has_table("ingestion_batches", schema="core")
    indexes = {
        i["name"]
        for i in inspector.get_indexes("finishing_measurements", "quality")
        if "duplicates_constraint" not in i
    }
    assert indexes == {
        "ix_finishing_measurements_source_date_desc",
        "ix_finishing_measurements_product_source_date",
        "ix_finishing_measurements_product_lot",
        "ix_finishing_measurements_current_record_key",
        "ix_finishing_measurements_current_source_date",
    }
    foreign_keys = inspector.get_foreign_keys("finishing_measurements", "quality")
    assert {(f["name"], f["referred_schema"], f["referred_table"]) for f in foreign_keys} == {
        ("fk_finishing_measurements_ingestion_batch", "core", "ingestion_batches"),
        ("fk_finishing_measurements_superseded_by_batch", "core", "ingestion_batches"),
    }
    batch_uniques = inspector.get_unique_constraints("ingestion_batches", "core")
    assert [(u["name"], u["column_names"]) for u in batch_uniques] == [
        ("uq_ingestion_batches_source_system_batch_id", ["source_system", "batch_id"])
    ]
    uniques = inspector.get_unique_constraints("finishing_measurements", "quality")
    assert [(u["name"], u["column_names"]) for u in uniques] == [
        (
            "uq_finishing_measurements_source_system_source_row_hash",
            ["source_system", "source_row_hash"],
        )
    ]
    with engine.connect() as connection:
        assert current_revision(connection) == HEAD


def test_version_table_is_in_core_not_public(engine: Engine) -> None:
    inspector = inspect(engine)

    assert inspector.has_table(ALEMBIC_VERSION_TABLE, schema="core")
    assert not inspector.has_table(ALEMBIC_VERSION_TABLE, schema="public")
    with engine.connect() as connection:
        versions = connection.execute(text("SELECT version_num FROM core.alembic_version"))
        assert versions.scalars().all() == [HEAD]


def test_model_matches_migration(engine: Engine) -> None:
    def include_name(name: str | None, type_: str, parent_names: object) -> bool:
        return name in MANAGED_SCHEMAS if type_ == "schema" else True

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_name": include_name,
                "compare_type": True,
                "version_table": ALEMBIC_VERSION_TABLE,
                "version_table_schema": ALEMBIC_VERSION_SCHEMA,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


@pytest.mark.destructive
def test_downgrades_remove_objects_and_upgrade_restores_them(engine: Engine) -> None:
    columns = ("source_record_key", "ingestion_batch_id", "superseded_at", "superseded_by_batch_id")
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "0001")
        inspector = inspect(connection)
        assert not inspector.has_table("ingestion_batches", schema="core")
        remaining = {c["name"] for c in inspector.get_columns("finishing_measurements", "quality")}
        assert remaining.isdisjoint(columns)
        assert current_revision(connection) == "0001"

        command.downgrade(alembic_config(connection), "base")
        inspector = inspect(connection)
        assert not inspector.has_table("finishing_measurements", schema="quality")
        assert inspector.has_table(ALEMBIC_VERSION_TABLE, schema="core")
        assert current_revision(connection) is None

        command.upgrade(alembic_config(connection), "head")
        inspector = inspect(connection)
        assert inspector.has_table("finishing_measurements", schema="quality")
        assert inspector.has_table("ingestion_batches", schema="core")
        assert current_revision(connection) == HEAD


@pytest.mark.destructive
def test_downgrade_refuses_to_discard_superseded_versions(engine: Engine) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            batch_pk = connection.scalar(
                insert(IngestionBatch)
                .values(
                    batch_id="downgrade-guard",
                    source_system=SOURCE,
                    connector_id="test",
                    extracted_at=SYNCED_AT,
                    received_at=SYNCED_AT,
                    status="accepted",
                    received_rows=1,
                    request_digest="0" * 64,
                )
                .returning(IngestionBatch.id)
            )
            connection.execute(
                insert(FinishingMeasurement).values(
                    source_date=dt.date(2026, 9, 1),
                    source_system=SOURCE,
                    source_row_hash="f" * 64,
                    synced_at=SYNCED_AT,
                    superseded_at=SYNCED_AT,
                    superseded_by_batch_id=batch_pk,
                )
            )
            with pytest.raises(Exception, match="superseded"):
                command.downgrade(alembic_config(connection), "0001")
        finally:
            transaction.rollback()
    with engine.connect() as connection:
        assert current_revision(connection) == HEAD


def test_created_at_has_server_default(session: Session) -> None:
    store(session, source_row())

    (row,) = stored_rows(session)
    assert row.created_at is not None
    assert row.created_at.tzinfo is not None
    assert row.synced_at == SYNCED_AT
    assert row.source_system == SOURCE
    assert row.source_row_hash == compute_source_row_hash(source_row())


# Null versus zero ---------------------------------------------------------------


def test_null_and_zero_measurements_are_stored_distinctly(session: Session) -> None:
    store(session, source_row(AvgOfMOISTURE=0.0, AvgOfCOLOR=None, AvgOfCombined_BD=0))

    (row,) = stored_rows(session)
    assert row.avg_moisture == Decimal(0)
    assert row.avg_moisture is not None
    assert row.avg_color is None
    assert row.avg_combined_bd == Decimal(0)

    zero_count = session.scalar(text("SELECT count(*) FROM quality.finishing_measurements "
                                     "WHERE avg_moisture = 0"))  # fmt: skip
    null_count = session.scalar(text("SELECT count(*) FROM quality.finishing_measurements "
                                     "WHERE avg_color IS NULL"))  # fmt: skip
    assert (zero_count, null_count) == (1, 1)


def test_repository_returns_zero_as_zero_and_null_as_null(session: Session) -> None:
    store(session, source_row(AvgOfMOISTURE=0.0, AvgOfCOLOR=None))

    (record,) = DatabaseMoistureRepository(session).matching(MoistureFilterParams())
    assert record.avg_moisture == 0
    assert record.avg_moisture is not None
    assert record.avg_color is None


def test_source_values_are_preserved_as_received(session: Session) -> None:
    store(
        session,
        source_row(AvgOfMOISTURE=0.43333333333333335, CAMPNO=26101, Location="  SILO 1 "),
    )

    (row,) = stored_rows(session)
    assert row.avg_moisture == Decimal("0.43333333333333335")
    assert row.campaign_no == "26101"
    assert row.location == "  SILO 1 "
    (record,) = DatabaseMoistureRepository(session).matching(MoistureFilterParams())
    assert record.avg_moisture == 0.43333333333333335


# Duplicate source hashes ---------------------------------------------------------


def test_reingesting_the_same_row_is_a_no_op(session: Session) -> None:
    assert store(session, source_row()) == 1
    assert store(session, source_row()) == 0
    # Same values delivered with different Python types.
    assert store(session, source_row(CAMPNO=26101, AvgOfCOLOR=Decimal("40.00"))) == 0
    assert len(stored_rows(session)) == 1


def test_duplicates_within_one_batch_are_stored_once(session: Session) -> None:
    assert store(session, source_row(), source_row()) == 1


def test_same_row_from_another_source_system_is_stored(session: Session) -> None:
    store(session, source_row())

    assert store(session, source_row(), source_system="other-system") == 1
    assert len(stored_rows(session)) == 2


def test_changed_values_produce_a_new_row(session: Session) -> None:
    store(session, source_row(AvgOfMOISTURE=None))

    assert store(session, source_row(AvgOfMOISTURE=0)) == 1
    assert store(session, source_row(Location="SILO 1")) == 1


def test_database_rejects_duplicate_source_hash(session: Session) -> None:
    def make() -> FinishingMeasurement:
        return FinishingMeasurement(
            source_date=dt.date(2026, 9, 1),
            source_system=SOURCE,
            source_row_hash="duplicate-hash",
            synced_at=SYNCED_AT,
        )

    session.add(make())
    session.flush()
    session.add(make())
    with pytest.raises(IntegrityError, match="uq_finishing_measurements_source_system"):
        session.flush()
    session.rollback()


# Repository reads and ordering ----------------------------------------------------


def test_recent_is_newest_first_with_insertion_order_tie_break(session: Session) -> None:
    store(
        session,
        source_row(DATE="2026-09-01", LOT="old"),
        source_row(DATE="2026-09-05", LOT="first-same-day"),
        source_row(DATE="2026-09-05", LOT="second-same-day"),
        source_row(DATE="2026-09-03", LOT="middle"),
    )
    repo = DatabaseMoistureRepository(session)

    records, total = repo.recent(MoistureFilterParams(), 50)

    assert lots(records) == ["second-same-day", "first-same-day", "middle", "old"]
    assert total == 4
    assert lots(repo.matching(MoistureFilterParams())) == [
        "old",
        "middle",
        "first-same-day",
        "second-same-day",
    ]


def test_recent_returns_latest_50(session: Session) -> None:
    start = dt.date(2026, 1, 1)
    store(
        session,
        *(
            source_row(DATE=(start + dt.timedelta(days=i)).isoformat(), LOT=f"L{i:03d}")
            for i in range(60)
        ),
    )

    records, total = DatabaseMoistureRepository(session).recent(MoistureFilterParams(), 50)

    assert total == 60
    assert len(records) == 50
    assert records[0].lot == "L059"
    assert records[-1].lot == "L010"


# Repository filtering ----------------------------------------------------------------


@pytest.fixture
def sample_repo(session: Session) -> DatabaseMoistureRepository:
    store(session, *SAMPLE_ROWS)
    return DatabaseMoistureRepository(session)


def matching_lots(repo: DatabaseMoistureRepository, **filters: Any) -> list[str | None]:
    return lots(repo.matching(MoistureFilterParams(**filters)))


def test_product_filter_is_exact(sample_repo: DatabaseMoistureRepository) -> None:
    assert matching_lots(sample_repo, product="PRD-A") == ["A260901-01", "A260903-03"]
    assert matching_lots(sample_repo, product="prd-a") == []


def test_location_filter_does_not_normalize(sample_repo: DatabaseMoistureRepository) -> None:
    assert matching_lots(sample_repo, location="Silo 1") == ["A260901-01"]
    assert matching_lots(sample_repo, location="SILO 1") == ["B260902-02"]


def test_date_filter_is_inclusive(sample_repo: DatabaseMoistureRepository) -> None:
    assert matching_lots(sample_repo, start_date="2026-09-02", end_date="2026-09-03") == [
        "B260902-02",
        "A260903-03",
    ]
    assert matching_lots(sample_repo, end_date="2026-09-01") == ["A260901-01"]


def test_search_matches_lot_or_campaign(sample_repo: DatabaseMoistureRepository) -> None:
    assert matching_lots(sample_repo, search="a2609") == ["A260901-01", "A260903-03"]
    assert matching_lots(sample_repo, search="26202") == [None]
    assert matching_lots(sample_repo, search="nomatch") == []


@pytest.mark.parametrize("wildcard", ["%", "_", "A2609%"])
def test_search_treats_like_wildcards_literally(
    sample_repo: DatabaseMoistureRepository, wildcard: str
) -> None:
    assert matching_lots(sample_repo, search=wildcard) == []


def test_filters_combine(sample_repo: DatabaseMoistureRepository) -> None:
    records, total = sample_repo.recent(
        MoistureFilterParams(product="PRD-A", location="Railcar", start_date="2026-09-02"), 50
    )
    assert lots(records) == ["A260903-03"]
    assert total == 1


def test_no_matches_returns_empty(sample_repo: DatabaseMoistureRepository) -> None:
    records, total = sample_repo.recent(MoistureFilterParams(product="NOPE"), 50)
    assert (records, total) == ([], 0)


def test_filter_options(session: Session) -> None:
    store(session, *SAMPLE_ROWS, source_row(DATE="2026-08-15", PRODUCT=None, Location=None))

    options = DatabaseMoistureRepository(session).filter_options()

    assert options.products == ["PRD-A", "PRD-B"]
    assert options.locations == ["Railcar", "SILO 1", "Silo 1", "Silo 2"]
    assert (options.date_range.min, options.date_range.max) == (
        dt.date(2026, 8, 15),
        dt.date(2026, 9, 4),
    )


def test_filter_options_on_empty_table(session: Session) -> None:
    options = DatabaseMoistureRepository(session).filter_options()

    assert (options.products, options.locations) == ([], [])
    assert (options.date_range.min, options.date_range.max) == (None, None)


# API contract ----------------------------------------------------------------------


def _client(repo: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_moisture_repository] = lambda: repo
    app.dependency_overrides[get_user_principal] = lambda: as_user(Permission.QUALITY_VIEW)
    return TestClient(app)


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/recent", {}),
        ("/recent", {"limit": 2}),
        ("/recent", {"product": "PRD-B"}),
        ("/recent", {"search": "a2609", "startDate": "2026-09-02"}),
        ("/trends", {}),
        ("/trends", {"location": "SILO 1"}),
        ("/filters", {}),
    ],
)
def test_database_and_fixture_return_the_same_contract(
    session: Session, path: str, params: dict[str, Any]
) -> None:
    store(session, *SAMPLE_ROWS)
    fixture_repo = FixtureMoistureRepository([record_from_source_row(r) for r in SAMPLE_ROWS])

    from_db = _client(DatabaseMoistureRepository(session)).get(BASE + path, params=params).json()
    from_fixture = _client(fixture_repo).get(BASE + path, params=params).json()

    assert from_db.pop("dataSource") == {
        "kind": "database",
        "isFixture": False,
        "label": "Operations database.",
    }
    from_fixture.pop("dataSource")
    assert from_db == from_fixture


def test_dependency_selects_database_when_configured(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TEST_DATABASE_URL
    monkeypatch.setattr(repository_module, "get_sessionmaker", lambda: sessionmaker(bind=engine))
    settings = Settings(
        _env_file=None, moisture_data_source="database", database_url=TEST_DATABASE_URL
    )

    dependency = get_moisture_repository(settings)
    repo = next(dependency)

    assert isinstance(repo, DatabaseMoistureRepository)
    assert repo.filter_options().products == []
    dependency.close()


def test_table_count_is_unaffected_by_reads(session: Session) -> None:
    store(session, *SAMPLE_ROWS)
    repo = DatabaseMoistureRepository(session)
    repo.recent(MoistureFilterParams(), 50)
    repo.matching(MoistureFilterParams())
    repo.filter_options()

    assert session.scalar(select(func.count()).select_from(FinishingMeasurement)) == 4
