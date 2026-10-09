"""Finishing batch ingestion against PostgreSQL (requires TEST_DATABASE_URL):
persistence, batch auditing, and correction semantics."""

import datetime as dt
import logging
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from principals import as_user
from sqlalchemy import Engine, delete, func, inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from test_finishing_ingestion import (
    URL,
    batch,
    enabled_settings,
    make_client,
    row,
    window,
)

from app.core.authorization import UserPrincipal, get_user_principal
from app.core.machine_auth import DEVELOPMENT_CONNECTOR_ID
from app.core.permissions import Permission
from app.ingestion.models import IngestionBatch
from app.quality.moisture import ingestion_service
from app.quality.moisture.ingestion_schemas import FinishingBatchIn
from app.quality.moisture.ingestion_service import BatchConflictError
from app.quality.moisture.models import FinishingMeasurement
from app.quality.moisture.repository import (
    DatabaseMoistureRepository,
    FinishingMeasurementWriter,
    get_moisture_repository,
)
from app.quality.moisture.schemas import MoistureFilterParams

pytestmark = requires_postgres


def quality_viewer() -> UserPrincipal:
    return as_user(Permission.QUALITY_VIEW)


SOURCE = "access-qryFINISHING-AVG"
T1 = "2026-10-02T08:00:00Z"
T2 = "2026-10-02T09:00:00Z"
T3 = "2026-10-02T10:00:00Z"


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """A connection whose outer transaction is rolled back after each test."""
    with engine.connect() as conn:
        transaction = conn.begin()
        yield conn
        transaction.rollback()


@pytest.fixture
def session_factory(connection: Connection) -> Any:
    # Each service transaction becomes a savepoint inside the test transaction.
    def factory() -> Session:
        return Session(bind=connection, join_transaction_mode="create_savepoint")

    return factory


@pytest.fixture
def client(session_factory: Any) -> Iterator[TestClient]:
    with make_client(enabled_settings(), session_factory=session_factory) as test_client:
        yield test_client


def query(connection: Connection, statement: Any) -> list[Any]:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        return list(session.scalars(statement))


def versions(connection: Connection) -> list[FinishingMeasurement]:
    return query(connection, select(FinishingMeasurement).order_by(FinishingMeasurement.id))


def current(connection: Connection) -> list[FinishingMeasurement]:
    m = FinishingMeasurement
    return query(connection, select(m).where(m.superseded_at.is_(None)).order_by(m.id))


def audits(connection: Connection) -> list[IngestionBatch]:
    return query(connection, select(IngestionBatch).order_by(IngestionBatch.id))


def count(connection: Connection) -> int:
    return connection.scalar(select(func.count()).select_from(FinishingMeasurement)) or 0


def post(client: TestClient, *rows: dict[str, Any], **overrides: Any) -> Any:
    overrides.setdefault("batchId", uuid.uuid4().hex)
    return client.post(URL, json=batch(*rows, **overrides))


def ingest(client: TestClient, *rows: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    response = post(client, *rows, **overrides)
    assert response.status_code == 200, response.text
    return response.json()


def counts(result: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        result["insertedRows"],
        result["duplicateRows"],
        result["restoredRows"],
        result["supersededRows"],
        result["rejectedRows"],
    )


# Persistence -------------------------------------------------------------------------


def test_valid_batch_is_stored(client: TestClient, connection: Connection) -> None:
    result = ingest(client, row(lot="L1"), row(lot="L2", sourceDate="2026-09-02"), batchId="b-1")

    assert result == {
        "batchId": "b-1",
        "sourceSystem": SOURCE,
        "status": "accepted",
        "receivedRows": 2,
        "insertedRows": 2,
        "duplicateRows": 0,
        "rejectedRows": 0,
        "restoredRows": 0,
        "supersededRows": 0,
        "windowApplied": None,
        "replayed": False,
        "rejections": [],
        "rejectionsTruncated": False,
    }
    first, second = versions(connection)
    assert (first.lot, second.lot) == ("L1", "L2")
    assert first.source_system == SOURCE
    assert first.avg_moisture == Decimal("0.4")
    assert first.synced_at.tzinfo is not None
    assert len(first.source_row_hash) == 64
    assert first.source_record_key is None
    assert first.ingestion_batch_id == audits(connection)[0].id
    assert first.superseded_at is None


def test_response_does_not_echo_measurements(client: TestClient) -> None:
    response = post(client, row(avgMoisture=0.987654321))

    assert "0.987654321" not in response.text


def test_null_measurement_is_stored_as_null(client: TestClient, connection: Connection) -> None:
    ingest(client, row(avgMoisture=None, avgColor=None, avgCombinedBd=None))

    (record,) = versions(connection)
    assert (record.avg_moisture, record.avg_color, record.avg_combined_bd) == (None, None, None)


def test_zero_measurement_is_stored_as_zero(client: TestClient, connection: Connection) -> None:
    ingest(client, row(avgMoisture=0, avgColor=0.0))

    (record,) = versions(connection)
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

    (record,) = versions(connection)
    assert record.avg_moisture == Decimal("0.1234567890123456789012345")
    assert record.avg_color == Decimal(-3)
    assert record.avg_combined_bd == Decimal("99999.5")
    assert (record.campaign_no, record.lot, record.location, record.product) == (
        "26101",
        "a-1 ",
        "  SILO 1 ",
        "prd-a",
    )


def test_identical_rows_in_new_batches_are_not_duplicated(
    client: TestClient, connection: Connection
) -> None:
    rows = [row(lot=f"L{i}") for i in range(3)]

    assert counts(ingest(client, *rows)) == (3, 0, 0, 0, 0)
    assert counts(ingest(client, *rows)) == (0, 3, 0, 0, 0)
    assert count(connection) == 3


def test_duplicate_rows_within_a_batch_are_stored_once(
    client: TestClient, connection: Connection
) -> None:
    result = ingest(client, row(), row(), row(campaignNo=26101, avgColor=40))

    assert counts(result) == (1, 2, 0, 0, 0)
    assert count(connection) == 1


def test_overlapping_batches_insert_only_new_rows(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, row(lot="L1"), row(lot="L2"))

    assert counts(ingest(client, row(lot="L2"), row(lot="L3"))) == (1, 1, 0, 0, 0)
    assert count(connection) == 3


def test_same_rows_from_another_source_system_are_stored(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, row())

    assert ingest(client, row(), sourceSystem="other-system")["insertedRows"] == 1
    assert count(connection) == 2


def test_valid_rows_are_stored_when_others_are_rejected(
    client: TestClient, connection: Connection
) -> None:
    result = ingest(client, row(lot="good"), row(sourceDate="bad"), row(avgColor="x"))

    assert result["status"] == "accepted_with_rejections"
    assert (result["receivedRows"], result["insertedRows"], result["rejectedRows"]) == (3, 1, 2)
    assert [r["rowIndex"] for r in result["rejections"]] == [1, 2]
    assert [r.lot for r in versions(connection)] == ["good"]


@pytest.mark.parametrize("value", ["2026-13-01", "09/01/2026", 20260901])
def test_batch_of_only_invalid_rows_is_rejected(
    client: TestClient, connection: Connection, value: Any
) -> None:
    result = ingest(client, row(sourceDate=value))

    assert result["status"] == "rejected"
    assert (result["rejectedRows"], result["insertedRows"]) == (1, 0)
    assert result["rejections"][0]["errors"][0]["field"] == "sourceDate"
    assert count(connection) == 0


def test_rejection_list_is_capped(client: TestClient) -> None:
    result = ingest(client, *[row(sourceDate="bad")] * 150)

    assert result["rejectedRows"] == 150
    assert len(result["rejections"]) == 100
    assert result["rejectionsTruncated"] is True


def test_rejections_do_not_echo_submitted_values(client: TestClient) -> None:
    response = post(client, row(avgMoisture="SUBMITTED-VALUE-123", lot=["LOT-VALUE-456"]))

    assert response.status_code == 200
    assert "SUBMITTED-VALUE-123" not in response.text
    assert "LOT-VALUE-456" not in response.text


class FailOnSecondChunk(FinishingMeasurementWriter):
    chunk_size = 1
    calls = 0

    def _insert_chunk(self, chunk: Any) -> int:
        type(self).calls += 1
        if type(self).calls == 2:
            raise OperationalError("INSERT", {}, Exception("simulated connection loss"))
        return super()._insert_chunk(chunk)


@pytest.fixture
def failing_writer(monkeypatch: pytest.MonkeyPatch) -> type[FailOnSecondChunk]:
    FailOnSecondChunk.calls = 0
    monkeypatch.setattr(ingestion_service, "FinishingMeasurementWriter", FailOnSecondChunk)
    return FailOnSecondChunk


def test_database_failure_rolls_back_the_whole_batch(
    client: TestClient, connection: Connection, failing_writer: type[FailOnSecondChunk]
) -> None:
    response = post(client, row(lot="L1"), row(lot="L2"), row(lot="L3"))

    assert failing_writer.calls == 2  # the first row was written before the failure
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
            audited = other.scalar(
                select(IngestionBatch.status).where(IngestionBatch.source_system == source_system)
            )
        assert (visible, audited) == (1, "accepted")
    finally:
        with engine.begin() as conn:
            conn.execute(
                delete(FinishingMeasurement).where(
                    FinishingMeasurement.source_system == source_system
                )
            )
            conn.execute(
                delete(IngestionBatch).where(IngestionBatch.source_system == source_system)
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
        client.app.dependency_overrides[get_user_principal] = quality_viewer
        api = client.get("/api/v1/quality/moisture/recent").json()

    assert total == 2
    assert [r.lot for r in records] == ["L-new", "L-old"]
    assert [(r["lot"], r["avgMoisture"]) for r in api["records"]] == [
        ("L-new", None),
        ("L-old", 0),
    ]
    assert api["dataSource"]["kind"] == "database"


# Batch auditing ------------------------------------------------------------------------


def test_successful_batch_is_audited(client: TestClient, connection: Connection) -> None:
    ingest(client, row(lot="L1"), row(lot="L1"), batchId="audit-1", extractedAt=T1)

    (record,) = audits(connection)
    assert (record.batch_id, record.source_system) == ("audit-1", SOURCE)
    assert record.connector_id == DEVELOPMENT_CONNECTOR_ID
    assert record.extracted_at == dt.datetime(2026, 10, 2, 8, 0, tzinfo=dt.UTC)
    assert record.received_at <= record.completed_at
    assert record.status == "accepted"
    assert (record.received_rows, record.inserted_rows, record.duplicate_rows) == (2, 1, 1)
    assert (record.rejected_rows, record.restored_rows, record.superseded_rows) == (0, 0, 0)
    assert (record.window_start, record.window_end, record.window_applied) == (None, None, None)
    assert record.error_code is None
    assert record.attempt_count == 1
    assert len(record.request_digest) == 64
    assert record.created_at is not None


def test_audit_table_holds_metadata_only(client: TestClient, connection: Connection) -> None:
    ingest(client, row(lot="LOT-NOT-AUDITED", location="LOCATION-NOT-AUDITED"))

    columns = {c["name"] for c in inspect(connection).get_columns("ingestion_batches", "core")}
    assert columns == {
        "id", "batch_id", "source_system", "connector_id", "extracted_at", "received_at",
        "completed_at", "status", "received_rows", "inserted_rows", "duplicate_rows",
        "rejected_rows", "restored_rows", "superseded_rows", "window_start", "window_end",
        "window_applied", "request_digest", "attempt_count", "error_code", "created_at",
    }  # fmt: skip
    (record,) = audits(connection)
    stored = " ".join(str(getattr(record, c)) for c in columns)
    assert "LOT-NOT-AUDITED" not in stored
    assert "LOCATION-NOT-AUDITED" not in stored


def test_partial_and_rejected_batches_are_audited(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, row(), row(sourceDate="bad"), batchId="partial")
    ingest(client, row(sourceDate="bad"), batchId="rejected")

    partial, rejected = audits(connection)
    assert (partial.status, partial.inserted_rows, partial.rejected_rows) == (
        "accepted_with_rejections",
        1,
        1,
    )
    assert (rejected.status, rejected.inserted_rows, rejected.rejected_rows) == ("rejected", 0, 1)


def test_failed_attempt_is_audited_and_can_be_retried(
    client: TestClient,
    connection: Connection,
    failing_writer: type[FailOnSecondChunk],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [row(lot="L1"), row(lot="L2"), row(lot="L3")]

    assert post(client, *rows, batchId="retry-1").status_code == 503

    (failed,) = audits(connection)
    assert (failed.status, failed.error_code) == ("failed", "database_error")
    assert failed.inserted_rows == 0
    assert failed.duplicate_rows is None
    assert failed.completed_at is not None

    monkeypatch.setattr(ingestion_service, "FinishingMeasurementWriter", FinishingMeasurementWriter)
    result = ingest(client, *rows, batchId="retry-1")

    assert result["insertedRows"] == 3
    (retried,) = audits(connection)
    assert (retried.status, retried.error_code, retried.attempt_count) == ("accepted", None, 2)


def test_resubmitting_a_completed_batch_replays_its_result(
    client: TestClient, connection: Connection
) -> None:
    rows = [row(lot="L1"), row(sourceDate="bad")]
    first = ingest(client, *rows, batchId="replay-1")

    second = ingest(client, *rows, batchId="replay-1")

    assert second["replayed"] is True
    assert {k: v for k, v in second.items() if k != "replayed"} == {
        k: v for k, v in first.items() if k != "replayed"
    }
    (record,) = audits(connection)
    assert record.attempt_count == 1
    assert count(connection) == 1


def test_reusing_a_batch_id_with_different_content_is_refused(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, row(lot="L1"), batchId="conflict-1")

    response = post(client, row(lot="L2"), batchId="conflict-1")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "batch_id_conflict"
    assert [r.lot for r in versions(connection)] == ["L1"]
    assert len(audits(connection)) == 1


def test_another_connector_cannot_reuse_a_batch_id(
    client: TestClient, session_factory: Any
) -> None:
    body = batch(row(), batchId="owned-1")
    ingest(client, row(), batchId="owned-1")

    with pytest.raises(BatchConflictError):
        ingestion_service.ingest_batch(
            FinishingBatchIn.model_validate(body), session_factory, connector_id="other"
        )


def test_batch_ids_are_unique_per_source_system(client: TestClient, connection: Connection) -> None:
    ingest(client, row(), batchId="shared-id")
    ingest(client, row(), batchId="shared-id", sourceSystem="other-system")

    assert [(a.source_system, a.batch_id) for a in audits(connection)] == [
        (SOURCE, "shared-id"),
        ("other-system", "shared-id"),
    ]


def test_batch_outcome_is_logged_without_row_values(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    post(
        client,
        row(sourceDate="bad", lot="LOT-SHOULD-NOT-BE-LOGGED"),
        row(avgColor="x"),
        batchId="log-1",
    )

    (record,) = [
        r for r in caplog.records if "event=finishing_ingestion result=rejected" in r.getMessage()
    ]
    message = record.getMessage()
    for expected in (
        "batch_id=log-1",
        f"source_system={SOURCE}",
        f"connector={DEVELOPMENT_CONNECTOR_ID}",
        "attempt=1",
        "received=2",
        "inserted=0",
        "duplicates=0",
        "rejected=2",
        "rejected_fields=avgColor:1,sourceDate:1",
    ):
        assert expected in message
    assert record.ingestion["rejected"] == 2
    assert "LOT-SHOULD-NOT-BE-LOGGED" not in caplog.text


def test_unknown_field_names_are_not_logged_verbatim(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    post(client, row(**{"injected field": 1}))

    assert "injected field" not in caplog.text
    assert "rejected_fields=other:1" in caplog.text


# Strategy B: authoritative date windows -----------------------------------------------

DAY1, DAY2, DAY3, DAY4 = "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"


def window_batch(
    client: TestClient, *rows: dict[str, Any], extracted_at: str, start: str = DAY1, end: str = DAY3
) -> dict[str, Any]:
    return ingest(client, *rows, extractedAt=extracted_at, reconciliationWindow=window(start, end))


def initial_window(client: TestClient) -> list[dict[str, Any]]:
    rows = [
        row(sourceDate=DAY1, lot="A1", avgMoisture=0.4),
        row(sourceDate=DAY2, lot="A2", avgMoisture=0.5),
        row(sourceDate=DAY3, lot="A3", avgMoisture=0.6),
    ]
    assert counts(window_batch(client, *rows, extracted_at=T1)) == (3, 0, 0, 0, 0)
    return rows


def current_values(connection: Connection) -> dict[str | None, Decimal | None]:
    return {r.lot: r.avg_moisture for r in current(connection)}


def test_changed_aggregate_supersedes_the_previous_version(
    client: TestClient, connection: Connection
) -> None:
    rows = initial_window(client)
    rows[1] = row(sourceDate=DAY2, lot="A2", avgMoisture=0.55)

    result = window_batch(client, *rows, extracted_at=T2)

    assert result["windowApplied"] is True
    assert counts(result) == (1, 2, 0, 1, 0)
    assert current_values(connection) == {
        "A1": Decimal("0.4"),
        "A2": Decimal("0.55"),
        "A3": Decimal("0.6"),
    }
    (old,) = [v for v in versions(connection) if v.superseded_at is not None]
    assert old.avg_moisture == Decimal("0.5")
    assert old.superseded_by_batch_id == audits(connection)[1].id
    assert count(connection) == 4


def test_row_missing_from_a_window_is_superseded_not_deleted(
    client: TestClient, connection: Connection
) -> None:
    rows = initial_window(client)

    result = window_batch(client, rows[0], rows[2], extracted_at=T2)

    assert counts(result) == (0, 2, 0, 1, 0)
    assert set(current_values(connection)) == {"A1", "A3"}
    assert count(connection) == 3


def test_rows_outside_the_window_are_untouched(client: TestClient, connection: Connection) -> None:
    initial_window(client)
    ingest(client, row(sourceDate=DAY4, lot="A4"))

    window_batch(client, row(sourceDate=DAY1, lot="A1", avgMoisture=0.4), extracted_at=T2)

    assert set(current_values(connection)) == {"A1", "A4"}


def test_reverted_correction_restores_the_earlier_version(
    client: TestClient, connection: Connection
) -> None:
    rows = initial_window(client)
    changed = [rows[0], row(sourceDate=DAY2, lot="A2", avgMoisture=0.55), rows[2]]
    window_batch(client, *changed, extracted_at=T2)

    result = window_batch(client, *rows, extracted_at=T3)

    assert counts(result) == (0, 2, 1, 1, 0)
    assert current_values(connection)["A2"] == Decimal("0.5")
    assert count(connection) == 4


def test_stale_window_is_refused(client: TestClient, connection: Connection) -> None:
    rows = initial_window(client)
    window_batch(client, rows[0], rows[1], extracted_at=T3)
    before = current_values(connection)

    response = post(
        client, *rows, extractedAt=T2, reconciliationWindow=window(DAY1, DAY3), batchId="stale-1"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "stale_batch"
    assert current_values(connection) == before
    stale = audits(connection)[-1]
    assert (stale.status, stale.error_code, stale.window_applied) == (
        "failed",
        "stale_batch",
        False,
    )


def test_older_window_that_does_not_overlap_is_not_stale(
    client: TestClient, connection: Connection
) -> None:
    window_batch(client, row(sourceDate=DAY3, lot="A3"), extracted_at=T3, start=DAY3, end=DAY3)

    result = window_batch(
        client, row(sourceDate=DAY1, lot="A1"), extracted_at=T1, start=DAY1, end=DAY2
    )

    assert result["windowApplied"] is True
    assert set(current_values(connection)) == {"A1", "A3"}


def test_window_with_rejected_rows_is_not_applied(
    client: TestClient, connection: Connection
) -> None:
    rows = initial_window(client)

    result = window_batch(
        client,
        rows[0],
        row(sourceDate=DAY2, lot="A2", avgMoisture="not a number"),
        extracted_at=T2,
    )

    assert result["status"] == "accepted_with_rejections"
    assert result["windowApplied"] is False
    assert result["supersededRows"] == 0
    assert set(current_values(connection)) == {"A1", "A2", "A3"}


def test_rows_outside_the_declared_window_are_rejected(
    client: TestClient, connection: Connection
) -> None:
    result = window_batch(
        client, row(sourceDate=DAY1, lot="A1"), row(sourceDate=DAY4, lot="A4"), extracted_at=T1
    )

    assert result["rejections"][0]["rowIndex"] == 1
    assert result["windowApplied"] is False
    assert set(current_values(connection)) == {"A1"}


def test_same_lot_on_different_dates_and_locations_are_distinct(
    client: TestClient, connection: Connection
) -> None:
    rows = [
        row(sourceDate=DAY1, lot="SAME", location="Silo 1", avgMoisture=0.4),
        row(sourceDate=DAY2, lot="SAME", location="Silo 1", avgMoisture=0.4),
        row(sourceDate=DAY2, lot="SAME", location="Silo 2", avgMoisture=0.4),
    ]
    window_batch(client, *rows, extracted_at=T1)
    rows[2] = row(sourceDate=DAY2, lot="SAME", location="Silo 2", avgMoisture=0.45)

    result = window_batch(client, *rows, extracted_at=T2)

    assert counts(result) == (1, 2, 0, 1, 0)
    assert sorted((r.source_date.day, r.location, r.avg_moisture) for r in current(connection)) == [
        (1, "Silo 1", Decimal("0.4")),
        (2, "Silo 1", Decimal("0.4")),
        (2, "Silo 2", Decimal("0.45")),
    ]


def test_window_audit_records_the_declared_range(
    client: TestClient, connection: Connection
) -> None:
    initial_window(client)

    (record,) = audits(connection)
    assert (record.window_start, record.window_end) == (dt.date(2026, 9, 1), dt.date(2026, 9, 3))
    assert record.window_applied is True


def test_moisture_api_serves_only_current_versions(
    client: TestClient, connection: Connection
) -> None:
    rows = initial_window(client)
    window_batch(client, rows[0], row(sourceDate=DAY2, lot="A2", avgMoisture=0.55), extracted_at=T2)

    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        client.app.dependency_overrides[get_moisture_repository] = lambda: (
            DatabaseMoistureRepository(session)
        )
        client.app.dependency_overrides[get_user_principal] = quality_viewer
        api = client.get("/api/v1/quality/moisture/recent").json()
        filters = client.get("/api/v1/quality/moisture/filters").json()

    assert [(r["lot"], r["avgMoisture"]) for r in api["records"]] == [("A2", 0.55), ("A1", 0.4)]
    assert api["totalMatching"] == 2
    assert filters["dateRange"] == {"min": DAY1, "max": DAY2}


def test_append_mode_never_supersedes(client: TestClient, connection: Connection) -> None:
    ingest(client, row(avgMoisture=0.5))

    result = ingest(client, row(avgMoisture=0.55))

    assert counts(result) == (1, 0, 0, 0, 0)
    assert len(current(connection)) == 2


# Strategy A: durable source record identity ------------------------------------------


def keyed(record_id: str, **overrides: Any) -> dict[str, Any]:
    return row(sourceRecordId=record_id, **overrides)


def test_new_version_of_a_record_supersedes_the_current_one(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, keyed("R1", avgMoisture=0.5), extractedAt=T1)

    result = ingest(client, keyed("R1", avgMoisture=0.55), extractedAt=T2)

    assert counts(result) == (1, 0, 0, 1, 0)
    (now,) = current(connection)
    assert (now.source_record_key, now.avg_moisture) == ("R1", Decimal("0.55"))
    assert count(connection) == 2


def test_record_identity_is_independent_of_its_values(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, keyed("R1", sourceDate=DAY1, lot="L"), extractedAt=T1)

    ingest(client, keyed("R1", sourceDate=DAY2, lot="L-corrected"), extractedAt=T2)

    (now,) = current(connection)
    assert (now.source_date, now.lot) == (dt.date(2026, 9, 2), "L-corrected")


def test_unchanged_record_is_a_duplicate(client: TestClient, connection: Connection) -> None:
    ingest(client, keyed("R1"), extractedAt=T1)

    assert counts(ingest(client, keyed("R1"), extractedAt=T2)) == (0, 1, 0, 0, 0)
    assert count(connection) == 1


def test_record_reverted_to_an_earlier_version_is_restored(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, keyed("R1", avgMoisture=0.5), extractedAt=T1)
    ingest(client, keyed("R1", avgMoisture=0.55), extractedAt=T2)

    result = ingest(client, keyed("R1", avgMoisture=0.5), extractedAt=T3)

    assert counts(result) == (0, 0, 1, 1, 0)
    (now,) = current(connection)
    assert now.avg_moisture == Decimal("0.5")
    assert now.ingestion_batch_id == audits(connection)[-1].id


def test_stale_record_version_is_refused(client: TestClient, connection: Connection) -> None:
    ingest(client, keyed("R1", avgMoisture=0.55), extractedAt=T2)

    response = post(client, keyed("R1", avgMoisture=0.5), extractedAt=T1)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "stale_batch"
    (now,) = current(connection)
    assert now.avg_moisture == Decimal("0.55")


def test_records_with_the_same_product_and_lot_stay_distinct(
    client: TestClient, connection: Connection
) -> None:
    ingest(client, keyed("R1", lot="SAME"), keyed("R2", lot="SAME"), extractedAt=T1)

    ingest(client, keyed("R1", lot="SAME", avgMoisture=0.9), extractedAt=T2)

    assert sorted((r.source_record_key, r.avg_moisture) for r in current(connection)) == [
        ("R1", Decimal("0.9")),
        ("R2", Decimal("0.4")),
    ]


def test_database_allows_one_current_version_per_record(session_factory: Any) -> None:
    def version(row_hash: str) -> FinishingMeasurement:
        return FinishingMeasurement(
            source_date=dt.date(2026, 9, 1),
            source_system=SOURCE,
            source_row_hash=row_hash,
            source_record_key="R1",
            synced_at=dt.datetime.now(dt.UTC),
        )

    with session_factory() as session:
        session.add_all([version("a" * 64), version("b" * 64)])
        with pytest.raises(IntegrityError, match="ix_finishing_measurements_current_record_key"):
            session.flush()
