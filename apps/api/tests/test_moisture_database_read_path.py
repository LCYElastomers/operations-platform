"""Moisture Analysis read path with MOISTURE_DATA_SOURCE=database (requires TEST_DATABASE_URL).

Rows are written through the real ingestion endpoint and read through the real
`get_moisture_repository` dependency, exactly as in production. Each test runs
inside one outer transaction that is rolled back afterwards.
"""

import datetime as dt
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from postgres_support import TEST_DATABASE_URL, requires_postgres
from principals import as_user
from sqlalchemy import Engine, delete
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from test_finishing_ingestion import URL, batch, row, window

from app.core.authorization import get_user_principal
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.ingestion.models import IngestionBatch
from app.main import create_app
from app.quality.moisture import repository as repository_module
from app.quality.moisture.ingestion_router import get_ingestion_session_factory
from app.quality.moisture.models import FinishingMeasurement

pytestmark = requires_postgres

BASE = "/api/v1/quality/moisture"
DATABASE_SOURCE = {"kind": "database", "isFixture": False, "label": "Operations database."}
T1 = "2026-10-02T08:00:00Z"
T2 = "2026-10-02T09:00:00Z"


def database_settings() -> Settings:
    assert TEST_DATABASE_URL
    return Settings(
        _env_file=None,
        environment="test",
        database_url=TEST_DATABASE_URL,
        moisture_data_source="database",
        ingestion_auth_mode="development-unauthenticated",
    )


def make_client(session_factory: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = database_settings
    app.dependency_overrides[get_ingestion_session_factory] = lambda: session_factory
    app.dependency_overrides[get_user_principal] = lambda: as_user(Permission.QUALITY_VIEW)
    # The read dependency itself is not overridden; only its session source is.
    monkeypatch.setattr(repository_module, "get_sessionmaker", lambda: session_factory)
    return TestClient(app)


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        transaction = conn.begin()
        # Start every test from an empty table; undone by the rollback.
        conn.execute(delete(FinishingMeasurement))
        conn.execute(delete(IngestionBatch))
        yield conn
        transaction.rollback()


@pytest.fixture
def client(connection: Connection, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def session_factory() -> Session:
        return Session(bind=connection, join_transaction_mode="create_savepoint")

    with make_client(session_factory, monkeypatch) as test_client:
        yield test_client


def ingest(client: TestClient, *rows: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    overrides.setdefault("batchId", uuid.uuid4().hex)
    response = client.post(URL, json=batch(*rows, **overrides))
    assert response.status_code == 200, response.text
    return response.json()


def get(client: TestClient, path: str, **params: Any) -> dict[str, Any]:
    response = client.get(BASE + path, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataSource"] == DATABASE_SOURCE
    return body


def recent_lots(client: TestClient, **params: Any) -> list[str | None]:
    return [r["lot"] for r in get(client, "/recent", **params)["records"]]


def trend_lots(client: TestClient, **params: Any) -> list[str | None]:
    return [lot["lot"] for lot in get(client, "/trends", **params)["lots"]]


SAMPLE = [
    row(sourceDate="2026-09-01", lot="A260901-01", campaignNo="26101", product="PRD-A",
        location="Silo 1"),
    row(sourceDate="2026-09-02", lot="B260902-02", campaignNo="26201", product="PRD-B",
        location="SILO 1"),
    row(sourceDate="2026-09-03", lot="A260903-03", campaignNo="26102", product="PRD-A",
        location="Railcar"),
    row(sourceDate="2026-09-04", lot=None, campaignNo="26202", product="PRD-B",
        location="Silo 2"),
]  # fmt: skip


@pytest.fixture
def sample(client: TestClient) -> TestClient:
    ingest(client, *SAMPLE)
    return client


# Empty database -----------------------------------------------------------------------


def test_empty_database(client: TestClient) -> None:
    recent = get(client, "/recent")
    trends = get(client, "/trends")
    filters = get(client, "/filters")

    assert (recent["records"], recent["totalMatching"], recent["limit"]) == ([], 0, 50)
    assert trends["lots"] == []
    assert get(client, "/lots")["totalMatching"] == 0
    assert trends["summary"] == {
        "lotCount": 0,
        "recordCount": 0,
        "avgMoisture": None,
        "avgColor": None,
        "avgCombinedBd": None,
        "moistureValueCount": 0,
        "colorValueCount": 0,
        "combinedBdValueCount": 0,
    }
    assert filters["products"] == []
    assert filters["locations"] == []
    assert filters["dateRange"] == {"min": None, "max": None}


# Ingestion followed by reads ---------------------------------------------------------


def test_ingested_rows_are_immediately_readable(client: TestClient) -> None:
    assert get(client, "/recent")["totalMatching"] == 0

    ingest(client, row(sourceDate="2026-09-01", lot="L1"), row(sourceDate="2026-09-02", lot="L2"))

    assert recent_lots(client) == ["L2", "L1"]
    assert trend_lots(client) == ["L1", "L2"]
    assert get(client, "/filters")["dateRange"] == {"min": "2026-09-01", "max": "2026-09-02"}


def test_committed_ingestion_is_visible_to_the_next_request(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Separate connections and real commits, as between a connector run and a dashboard load.
    source_system = "read-path-commit-test"
    product = f"PRD-{uuid.uuid4().hex[:8]}"
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with make_client(factory, monkeypatch) as client:
            ingest(client, row(product=product, lot="COMMITTED-1"), sourceSystem=source_system)
        with make_client(factory, monkeypatch) as reader:
            body = get(reader, "/recent", product=product)
            filters = get(reader, "/filters")
        assert [r["lot"] for r in body["records"]] == ["COMMITTED-1"]
        assert product in filters["products"]
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


# Current versions only ----------------------------------------------------------------


def superseding_history(client: TestClient) -> None:
    """Two window extractions: one row corrected, one row removed at the source."""
    span = window("2026-09-01", "2026-09-05")
    kept = row(sourceDate="2026-09-01", lot="L-KEPT", product="PRD-A", location="Silo 1",
               avgMoisture=0.4)  # fmt: skip
    corrected_old = row(sourceDate="2026-09-03", lot="L-FIX", product="PRD-B",
                        location="SILO 1", avgMoisture=0.5)  # fmt: skip
    corrected_new = {**corrected_old, "avgMoisture": 0}
    removed = row(sourceDate="2026-09-05", lot="L-GONE", campaignNo="99999",
                  product="PRD-GONE", location="Gone Silo", avgMoisture=0.9)  # fmt: skip

    first = ingest(client, kept, corrected_old, removed, extractedAt=T1, reconciliationWindow=span)
    second = ingest(client, kept, corrected_new, extractedAt=T2, reconciliationWindow=span)

    assert first["insertedRows"] == 3
    assert (second["insertedRows"], second["duplicateRows"], second["supersededRows"]) == (1, 1, 2)
    assert second["windowApplied"] is True


def test_superseded_versions_never_appear_in_recent(client: TestClient) -> None:
    superseding_history(client)

    body = get(client, "/recent")

    assert [(r["lot"], r["avgMoisture"]) for r in body["records"]] == [
        ("L-FIX", 0),
        ("L-KEPT", 0.4),
    ]
    assert body["totalMatching"] == 2


def test_superseded_versions_never_appear_in_trends(client: TestClient) -> None:
    superseding_history(client)

    body = get(client, "/trends")

    assert [(lot["lot"], lot["avgMoisture"]) for lot in body["lots"]] == [
        ("L-KEPT", 0.4),
        ("L-FIX", 0),
    ]
    assert body["summary"]["lotCount"] == 2
    assert body["summary"]["recordCount"] == 2
    assert body["summary"]["avgMoisture"] == pytest.approx(0.2)


def test_superseded_versions_never_appear_in_filters(client: TestClient) -> None:
    superseding_history(client)

    body = get(client, "/filters")

    assert body["products"] == ["PRD-A", "PRD-B"]
    assert body["locations"] == ["SILO 1", "Silo 1"]
    assert body["dateRange"] == {"min": "2026-09-01", "max": "2026-09-03"}


@pytest.mark.parametrize(
    "params",
    [
        {"product": "PRD-GONE"},
        {"location": "Gone Silo"},
        {"search": "L-GONE"},
        {"search": "99999"},
        {"startDate": "2026-09-05", "endDate": "2026-09-05"},
    ],
)
def test_superseded_versions_cannot_be_reached_by_filtering(
    client: TestClient, params: dict[str, str]
) -> None:
    superseding_history(client)

    assert get(client, "/recent", **params)["totalMatching"] == 0
    assert get(client, "/lots", **params)["totalMatching"] == 0
    assert get(client, "/trends", **params)["lots"] == []


# Values are passed through unchanged --------------------------------------------------


def test_null_and_zero_stay_distinct(client: TestClient) -> None:
    ingest(
        client,
        row(sourceDate="2026-09-01", lot="ZERO", avgMoisture=0, avgColor=None, avgCombinedBd=0.0),
        row(sourceDate="2026-09-02", lot="NULL", avgMoisture=None, avgColor=None,
            avgCombinedBd=None),
    )  # fmt: skip

    records = {r["lot"]: r for r in get(client, "/recent")["records"]}
    summary = get(client, "/trends")["summary"]

    assert (records["ZERO"]["avgMoisture"], records["ZERO"]["avgCombinedBd"]) == (0, 0)
    assert records["ZERO"]["avgColor"] is None
    assert records["NULL"]["avgMoisture"] is None
    assert records["NULL"]["avgCombinedBd"] is None
    assert (summary["recordCount"], summary["moistureValueCount"]) == (2, 1)
    assert summary["avgMoisture"] == 0
    assert (summary["avgColor"], summary["colorValueCount"]) == (None, 0)


def test_source_values_are_not_normalized(client: TestClient) -> None:
    ingest(
        client,
        row(campaignNo="00123", lot="260901", product="007", location="  SILO 1 ",
            avgMoisture=0.43333333333333335),
    )  # fmt: skip

    (record,) = get(client, "/recent")["records"]
    filters = get(client, "/filters")

    assert record["campaignNo"] == "00123"
    assert record["lot"] == "260901"
    assert record["product"] == "007"
    assert record["location"] == "  SILO 1 "
    assert record["avgMoisture"] == 0.43333333333333335
    assert (filters["products"], filters["locations"]) == (["007"], ["  SILO 1 "])
    assert recent_lots(client, location="  SILO 1 ") == ["260901"]
    assert recent_lots(client, location="SILO 1") == []
    assert recent_lots(client, product="7") == []


def test_records_carry_no_classification_or_specification(client: TestClient) -> None:
    ingest(client, row())

    (record,) = get(client, "/recent")["records"]

    assert set(record) == {
        "date",
        "campaignNo",
        "lot",
        "location",
        "product",
        "avgMoisture",
        "avgColor",
        "avgCombinedBd",
    }


# Filtering --------------------------------------------------------------------------


def test_product_filter_is_exact(sample: TestClient) -> None:
    assert recent_lots(sample, product="PRD-A") == ["A260903-03", "A260901-01"]
    assert trend_lots(sample, product="PRD-A") == ["A260901-01", "A260903-03"]
    assert recent_lots(sample, product="prd-a") == []


def test_location_filter_matches_raw_source_values(sample: TestClient) -> None:
    assert recent_lots(sample, location="Silo 1") == ["A260901-01"]
    assert recent_lots(sample, location="SILO 1") == ["B260902-02"]
    assert trend_lots(sample, location="Silo 2") == [None]


def test_search_matches_lot_or_campaign_case_insensitively(sample: TestClient) -> None:
    assert recent_lots(sample, search="a2609") == ["A260903-03", "A260901-01"]
    assert recent_lots(sample, search="26202") == [None]
    assert trend_lots(sample, search="b260902") == ["B260902-02"]
    assert recent_lots(sample, search="%") == []


def test_date_filter_is_inclusive(sample: TestClient) -> None:
    assert recent_lots(sample, startDate="2026-09-02", endDate="2026-09-03") == [
        "A260903-03",
        "B260902-02",
    ]
    assert trend_lots(sample, endDate="2026-09-01") == ["A260901-01"]
    assert get(sample, "/recent", startDate="2026-09-05")["totalMatching"] == 0


def test_filters_combine(sample: TestClient) -> None:
    body = get(sample, "/recent", product="PRD-A", location="Railcar", startDate="2026-09-02")

    assert ([r["lot"] for r in body["records"]], body["totalMatching"]) == (["A260903-03"], 1)


def test_filters_endpoint_is_derived_from_current_records(client: TestClient) -> None:
    ingest(client, *SAMPLE, row(sourceDate="2026-08-15", lot="NO-NAMES", product=None,
                                location=None))  # fmt: skip

    body = get(client, "/filters")

    assert body["products"] == ["PRD-A", "PRD-B"]
    assert body["locations"] == ["Railcar", "SILO 1", "Silo 1", "Silo 2"]
    assert body["dateRange"] == {"min": "2026-08-15", "max": "2026-09-04"}


# Ordering and limits -------------------------------------------------------------------


def test_recent_is_newest_first_and_trends_oldest_first(client: TestClient) -> None:
    ingest(
        client,
        row(sourceDate="2026-09-01", lot="old"),
        row(sourceDate="2026-09-05", lot="first-same-day"),
        row(sourceDate="2026-09-05", lot="second-same-day"),
        row(sourceDate="2026-09-03", lot="middle"),
    )

    assert recent_lots(client) == ["second-same-day", "first-same-day", "middle", "old"]
    assert trend_lots(client) == ["old", "middle", "first-same-day", "second-same-day"]


def test_recent_returns_the_latest_50_by_default(client: TestClient) -> None:
    start = dt.date(2026, 1, 1)
    ingest(
        client,
        *(
            row(sourceDate=(start + dt.timedelta(days=i)).isoformat(), lot=f"L{i:03d}")
            for i in range(60)
        ),
    )

    body = get(client, "/recent")

    assert (body["limit"], body["totalMatching"], len(body["records"])) == (50, 60, 50)
    assert body["records"][0]["lot"] == "L059"
    assert body["records"][-1]["lot"] == "L010"
    assert len(get(client, "/recent", limit=500)["records"]) == 60
    assert len(get(client, "/trends")["lots"]) == 60


def test_location_records_of_a_lot_form_one_master_row(client: TestClient) -> None:
    ingest(
        client,
        row(sourceDate="2026-09-01", product="3411", lot="260932010", location="PKG/0",
            avgMoisture=0.2),
        row(sourceDate="2026-09-01", product="3411", lot="260932010", location="SILO/1",
            avgMoisture=0),
        row(sourceDate="2026-09-02", product="3411", lot="260932010", location="PKG/1",
            avgMoisture=None),
    )  # fmt: skip

    body = get(client, "/lots")
    (lot,) = body["lots"]

    assert body["totalMatching"] == 1
    assert (lot["recordCount"], lot["moistureValueCount"]) == (3, 2)
    assert lot["avgMoisture"] == pytest.approx(0.1)
    assert [r["location"] for r in lot["records"]] == ["PKG/0", "SILO/1", "PKG/1"]
    assert get(client, "/trends")["summary"]["lotCount"] == 1


@pytest.mark.parametrize("limit", [0, 501])
def test_recent_limit_bounds_are_unchanged(client: TestClient, limit: int) -> None:
    assert client.get(f"{BASE}/recent", params={"limit": limit}).status_code == 422


def test_invalid_date_range_is_rejected(client: TestClient) -> None:
    response = client.get(
        f"{BASE}/recent", params={"startDate": "2026-09-02", "endDate": "2026-09-01"}
    )

    assert response.status_code == 422
