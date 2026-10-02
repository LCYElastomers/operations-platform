"""Finishing batch ingestion against PostgreSQL (requires TEST_DATABASE_URL)."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from test_finishing_ingestion import URL, batch, enabled_settings, make_client, row

from app.quality.moisture import ingestion_service
from app.quality.moisture.models import FinishingMeasurement
from app.quality.moisture.repository import (
    DatabaseMoistureRepository,
    FinishingMeasurementWriter,
    get_moisture_repository,
)
from app.quality.moisture.schemas import MoistureFilterParams

pytestmark = requires_postgres


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """A connection whose outer transaction is rolled back after each test."""
    with engine.connect() as conn:
        transaction = conn.begin()
        yield conn
        transaction.rollback()


@pytest.fixture
def client(connection: Connection) -> Iterator[TestClient]:
    # Each request's transaction becomes a savepoint inside the test transaction.
    def session_factory() -> Session:
        return Session(bind=connection, join_transaction_mode="create_savepoint")

    with make_client(enabled_settings(), session_factory=session_factory) as test_client:
        yield test_client


def stored(connection: Connection) -> list[FinishingMeasurement]:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        return list(session.scalars(select(FinishingMeasurement).order_by(FinishingMeasurement.id)))


def count(connection: Connection) -> int:
    return connection.scalar(select(func.count()).select_from(FinishingMeasurement)) or 0


def ingest(client: TestClient, *rows: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    response = client.post(URL, json=batch(*rows, **overrides))
    assert response.status_code == 200, response.text
    return response.json()


def test_valid_batch_is_stored(client: TestClient, connection: Connection) -> None:
    result = ingest(client, row(lot="L1"), row(lot="L2", sourceDate="2026-09-02"))

    assert result == {
        "batchId": "batch-0001",
        "sourceSystem": "access-qryFINISHING-AVG",
        "status": "accepted",
        "receivedRows": 2,
        "insertedRows": 2,
        "duplicateRows": 0,
        "rejectedRows": 0,
        "rejections": [],
        "rejectionsTruncated": False,
    }
    first, second = stored(connection)
    assert (first.lot, second.lot) == ("L1", "L2")
    assert first.source_system == "access-qryFINISHING-AVG"
    assert first.avg_moisture == Decimal("0.4")
    assert first.synced_at.tzinfo is not None
    assert len(first.source_row_hash) == 64


def test_response_does_not_echo_measurements(client: TestClient) -> None:
    response = client.post(URL, json=batch(row(avgMoisture=0.987654321)))

    assert "0.987654321" not in response.text


def test_null_measurement_is_stored_as_null(client: TestClient, connection: Connection) -> None:
    ingest(client, row(avgMoisture=None, avgColor=None, avgCombinedBd=None))

    (record,) = stored(connection)
    assert (record.avg_moisture, record.avg_color, record.avg_combined_bd) == (None, None, None)


def test_zero_measurement_is_stored_as_zero(client: TestClient, connection: Connection) -> None:
    ingest(client, row(avgMoisture=0, avgColor=0.0))

    (record,) = stored(connection)
    assert record.avg_moisture == Decimal(0)
    assert record.avg_moisture is not None
    assert record.avg_color == Decimal(0)


def test_exact_values_are_stored(client: TestClient, connection: Connection) -> None:
    response = client.post(
        URL,
        content=(
            b'{"sourceSystem": "access", "batchId": "b1", "extractedAt": "2026-10-02T16:00:00Z",'
            b' "rows": [{"sourceDate": "2026-09-01", "campaignNo": 26101, "lot": "a-1 ",'
            b' "location": "  SILO 1 ", "product": "prd-a",'
            b' "avgMoisture": 0.1234567890123456789012345, "avgColor": -3,'
            b' "avgCombinedBd": 99999.5}]}'
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200, response.text

    (record,) = stored(connection)
    assert record.avg_moisture == Decimal("0.1234567890123456789012345")
    assert record.avg_color == Decimal(-3)
    assert record.avg_combined_bd == Decimal("99999.5")
    assert (record.campaign_no, record.lot, record.location, record.product) == (
        "26101",
        "a-1 ",
        "  SILO 1 ",
        "prd-a",
    )


def test_duplicate_batch_submission_is_idempotent(
    client: TestClient, connection: Connection
) -> None:
    rows = [row(lot=f"L{i}") for i in range(3)]

    first = ingest(client, *rows)
    second = ingest(client, *rows)
    third = ingest(client, *rows, batchId="batch-0002")

    assert (first["insertedRows"], first["duplicateRows"]) == (3, 0)
    assert (second["insertedRows"], second["duplicateRows"]) == (0, 3)
    assert (third["insertedRows"], third["duplicateRows"]) == (0, 3)
    assert second["status"] == "accepted"
    assert count(connection) == 3


def test_duplicate_rows_within_a_batch_are_stored_once(
    client: TestClient, connection: Connection
) -> None:
    result = ingest(client, row(), row(), row(campaignNo=26101, avgColor=40))

    assert (result["insertedRows"], result["duplicateRows"]) == (1, 2)
    assert count(connection) == 1


def test_overlapping_batches_insert_only_new_rows(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, row(lot="L1"), row(lot="L2"))

    result = ingest(client, row(lot="L2"), row(lot="L3"))

    assert (result["insertedRows"], result["duplicateRows"]) == (1, 1)
    assert count(connection) == 3


def test_same_rows_from_another_source_system_are_stored(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, row())

    result = ingest(client, row(), sourceSystem="other-system")

    assert result["insertedRows"] == 1
    assert count(connection) == 2


def test_changed_value_is_a_new_row(client: TestClient, connection: Connection) -> None:
    ingest(client, row(avgMoisture=None))

    assert ingest(client, row(avgMoisture=0))["insertedRows"] == 1
    assert count(connection) == 2


def test_valid_rows_are_stored_when_others_are_rejected(
    client: TestClient, connection: Connection
) -> None:
    result = ingest(client, row(lot="good"), row(sourceDate="bad"), row(avgColor="x"))

    assert result["status"] == "accepted_with_rejections"
    assert (result["receivedRows"], result["insertedRows"], result["rejectedRows"]) == (3, 1, 2)
    assert [r["rowIndex"] for r in result["rejections"]] == [1, 2]
    assert [r.lot for r in stored(connection)] == ["good"]


class FailOnSecondChunk(FinishingMeasurementWriter):
    chunk_size = 1
    calls = 0

    def _insert_chunk(self, chunk: Any) -> int:
        type(self).calls += 1
        if type(self).calls == 2:
            raise OperationalError("INSERT", {}, Exception("simulated connection loss"))
        return super()._insert_chunk(chunk)


def test_database_failure_rolls_back_the_whole_batch(
    client: TestClient, connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    FailOnSecondChunk.calls = 0
    monkeypatch.setattr(ingestion_service, "FinishingMeasurementWriter", FailOnSecondChunk)

    response = client.post(URL, json=batch(row(lot="L1"), row(lot="L2"), row(lot="L3")))

    assert FailOnSecondChunk.calls == 2  # the first row was written before the failure
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"
    assert count(connection) == 0


def test_large_batches_are_written_in_chunks(client: TestClient, connection: Connection) -> None:
    result = ingest(client, *[row(lot=f"L{i:04d}") for i in range(2500)])

    assert result["insertedRows"] == 2500
    assert count(connection) == 2500


def test_committed_batch_is_visible_to_other_connections(engine: Engine) -> None:
    source_system = "ingestion-commit-test"
    try:
        with make_client(enabled_settings(), session_factory=sessionmaker(bind=engine)) as client:
            ingest(client, row(), sourceSystem=source_system)

        with engine.connect() as other:
            visible = other.scalar(
                select(func.count())
                .select_from(FinishingMeasurement)
                .where(FinishingMeasurement.source_system == source_system)
            )
        assert visible == 1
    finally:
        with engine.begin() as conn:
            conn.execute(
                delete(FinishingMeasurement).where(
                    FinishingMeasurement.source_system == source_system
                )
            )


def test_ingested_rows_are_served_by_the_moisture_api(
    client: TestClient, connection: Connection
) -> None:
    ingest(
        client,
        row(lot="L-old", sourceDate="2026-09-01", avgMoisture=0),
        row(lot="L-new", sourceDate="2026-09-03", avgMoisture=None),
    )
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        repository = DatabaseMoistureRepository(session)
        records, total = repository.recent(MoistureFilterParams(), 50)
        client.app.dependency_overrides[get_moisture_repository] = lambda: repository
        api = client.get("/api/v1/quality/moisture/recent").json()

    assert total == 2
    assert [r.lot for r in records] == ["L-new", "L-old"]
    assert [(r["lot"], r["avgMoisture"]) for r in api["records"]] == [
        ("L-new", None),
        ("L-old", 0),
    ]
    assert api["dataSource"]["kind"] == "database"
