"""Finishing batch ingestion: authentication, validation, hashing, and failure
handling. No database required; persistence is covered in
test_finishing_ingestion_database.py."""

import datetime as dt
import json
import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.main import create_app
from app.quality.moisture.ingestion import compute_source_row_hash
from app.quality.moisture.ingestion_router import (
    MAX_BODY_BYTES,
    _parse_json,
    get_ingestion_session_factory,
)
from app.quality.moisture.ingestion_schemas import MAX_BATCH_ROWS
from app.quality.moisture.ingestion_service import validate_rows

URL = "/api/v1/ingestion/quality/finishing/batches"
SYNCED_AT = dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.UTC)
# Placeholder only: nothing listens on port 1, so connections fail immediately.
UNREACHABLE_DB = "postgresql+psycopg://ingest_test:not-a-real-password@127.0.0.1:1/none_test"


def row(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "sourceDate": "2026-09-01",
        "campaignNo": "26101",
        "lot": "A260901-01",
        "location": "Silo 1",
        "product": "PRD-A",
        "avgMoisture": 0.4,
        "avgColor": 40.0,
        "avgCombinedBd": 0.7,
    }
    data.update(overrides)
    return data


def batch(*rows: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "sourceSystem": "access-qryFINISHING-AVG",
        "batchId": "batch-0001",
        "extractedAt": "2026-10-02T11:00:00-05:00",
        "rows": list(rows) if rows else [row()],
    }
    data.update(overrides)
    return data


def enabled_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "ingestion_auth_mode": "development-unauthenticated",
        "database_url": UNREACHABLE_DB,
    }
    values.update(overrides)
    return Settings(**values)


def no_database() -> Session:
    raise AssertionError("the database must not be used")


def make_client(settings: Settings, session_factory: Any = no_database) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ingestion_session_factory] = lambda: session_factory
    return TestClient(app)


@pytest.fixture
def enabled() -> Iterator[TestClient]:
    with make_client(enabled_settings()) as client:
        yield client


def validated(*rows: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    parsed = _parse_json(json.dumps(list(rows)).encode())
    return validate_rows(parsed, source_system="access", synced_at=SYNCED_AT)


# Authentication fails closed ------------------------------------------------------


def test_ingestion_is_disabled_by_default() -> None:
    with make_client(Settings(_env_file=None)) as client:
        response = client.post(URL, json=batch())

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "ingestion_disabled"


def test_disabled_ingestion_rejects_before_reading_the_body() -> None:
    with make_client(Settings(_env_file=None)) as client:
        response = client.post(URL, content=b"not json", headers={"content-type": "text/plain"})

    assert response.status_code == 503


def test_development_mode_is_refused_in_production_settings() -> None:
    with pytest.raises(ValueError, match="not allowed in production"):
        enabled_settings(environment="production")


def test_dependency_fails_closed_in_production_even_if_settings_bypass_validation() -> None:
    settings = Settings.model_construct(
        environment="production", ingestion_auth_mode="development-unauthenticated"
    )
    with make_client(settings) as client:
        response = client.post(URL, json=batch())

    assert response.status_code == 503


def test_enabling_ingestion_requires_a_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="requires DATABASE_URL"):
        enabled_settings(database_url=None)


def test_unknown_auth_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        enabled_settings(ingestion_auth_mode="api-key")


def test_ingestion_is_post_only(enabled: TestClient) -> None:
    assert enabled.get(URL).status_code == 405


# Request-level validation (nothing processed) -----------------------------------------


def test_empty_batch_is_rejected(enabled: TestClient) -> None:
    response = enabled.post(URL, json=batch(rows=[]))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "validation_error"
    assert [e["field"] for e in detail["errors"]] == ["rows"]


def test_too_many_rows_are_rejected(enabled: TestClient) -> None:
    response = enabled.post(URL, json=batch(rows=[row()] * (MAX_BATCH_ROWS + 1)))

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"sourceSystem": ""}, "sourceSystem"),
        ({"sourceSystem": "access\nforged log line"}, "sourceSystem"),
        ({"batchId": "x" * 101}, "batchId"),
        ({"batchId": None}, "batchId"),
        ({"extractedAt": "2026-10-02T11:00:00"}, "extractedAt"),
        ({"extractedAt": "yesterday"}, "extractedAt"),
        ({"rows": {"0": {}}}, "rows"),
        ({"unexpected": 1}, "unexpected"),
    ],
)
def test_invalid_batch_metadata_is_rejected(
    enabled: TestClient, overrides: dict[str, Any], field: str
) -> None:
    response = enabled.post(URL, json=batch(**overrides))

    assert response.status_code == 422
    assert field in [e["field"] for e in response.json()["detail"]["errors"]]


def test_missing_batch_metadata_is_rejected(enabled: TestClient) -> None:
    body = batch()
    del body["sourceSystem"]

    response = enabled.post(URL, json=body)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        b"{not json",
        b'{"sourceSystem": "a", "sourceSystem": "b"}',
        b'{"rows": [{"avgMoisture": NaN}]}',
        b'{"rows": [{"avgMoisture": Infinity}]}',
        b"\xff\xfe",
    ],
)
def test_malformed_json_is_rejected(enabled: TestClient, body: bytes) -> None:
    response = enabled.post(URL, content=body, headers={"content-type": "application/json"})

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_json"


def test_non_json_content_type_is_rejected(enabled: TestClient) -> None:
    response = enabled.post(
        URL, content=json.dumps(batch()), headers={"content-type": "text/plain"}
    )

    assert response.status_code == 415


def test_oversized_body_is_rejected(enabled: TestClient) -> None:
    response = enabled.post(
        URL,
        content=b" " * (MAX_BODY_BYTES + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413


# Row-level validation ---------------------------------------------------------------


def post_rows(client: TestClient, *rows: dict[str, Any]) -> dict[str, Any]:
    response = client.post(URL, json=batch(*rows))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "value",
    ["2026-13-01", "2026-02-30", "09/01/2026", "2026-9-1", "2026-09-01T10:00:00", 20260901, ""],
)
def test_malformed_dates_are_rejected(enabled: TestClient, value: Any) -> None:
    result = post_rows(enabled, row(sourceDate=value))

    assert result["status"] == "rejected"
    assert result["rejectedRows"] == 1
    assert result["insertedRows"] == 0
    assert result["rejections"][0]["rowIndex"] == 0
    assert result["rejections"][0]["errors"][0]["field"] == "sourceDate"


@pytest.mark.parametrize("value", ["abc", "0.5", "", True, [0.5], {"value": 0.5}])
def test_malformed_numeric_measurements_are_rejected(enabled: TestClient, value: Any) -> None:
    result = post_rows(enabled, row(avgMoisture=value))

    assert result["rejectedRows"] == 1
    assert result["rejections"][0]["errors"][0]["field"] == "avgMoisture"


@pytest.mark.parametrize("value", [None, "missing"])
def test_missing_source_date_is_rejected(enabled: TestClient, value: Any) -> None:
    data = row(sourceDate=value)
    if value == "missing":
        del data["sourceDate"]

    result = post_rows(enabled, data)

    assert result["rejectedRows"] == 1
    assert result["rejections"][0]["errors"][0]["field"] == "sourceDate"


def test_measurement_fields_must_be_present_even_when_null(enabled: TestClient) -> None:
    data = row()
    del data["avgColor"]

    result = post_rows(enabled, data)

    assert result["rejections"][0]["errors"][0]["field"] == "avgColor"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lot", 12.5),
        ("product", ["PRD-A"]),
        ("location", "x" * 201),
        ("campaignNo", "26\x00101"),
        ("unknownField", "x"),
    ],
)
def test_invalid_identifiers_and_unknown_fields_are_rejected(
    enabled: TestClient, field: str, value: Any
) -> None:
    result = post_rows(enabled, row(**{field: value}))

    assert result["rejections"][0]["errors"][0]["field"] == field


def test_non_object_rows_are_rejected(enabled: TestClient) -> None:
    result = post_rows(enabled, "not a row", 42)  # type: ignore[arg-type]

    assert result["rejectedRows"] == 2
    assert [r["rowIndex"] for r in result["rejections"]] == [0, 1]


def test_rejections_report_every_problem_in_a_row(enabled: TestClient) -> None:
    result = post_rows(enabled, row(sourceDate="bad", avgColor="bad"))

    fields = {e["field"] for e in result["rejections"][0]["errors"]}
    assert fields == {"sourceDate", "avgColor"}


def test_rejections_do_not_echo_submitted_values(enabled: TestClient) -> None:
    response = enabled.post(
        URL, json=batch(row(avgMoisture="SUBMITTED-VALUE-123", lot=["LOT-VALUE-456"]))
    )

    assert "SUBMITTED-VALUE-123" not in response.text
    assert "LOT-VALUE-456" not in response.text


def test_rejection_list_is_capped(enabled: TestClient) -> None:
    result = post_rows(enabled, *[row(sourceDate="bad")] * 150)

    assert result["rejectedRows"] == 150
    assert len(result["rejections"]) == 100
    assert result["rejectionsTruncated"] is True


def test_mismatched_source_row_hash_is_rejected(enabled: TestClient) -> None:
    result = post_rows(enabled, row(sourceRowHash="0" * 64))

    assert result["rejections"][0]["errors"][0] == {
        "field": "sourceRowHash",
        "message": "does not match the row values",
    }


def test_malformed_source_row_hash_is_rejected(enabled: TestClient) -> None:
    result = post_rows(enabled, row(sourceRowHash="ABC"))

    assert result["rejections"][0]["errors"][0]["field"] == "sourceRowHash"


# Values are preserved -------------------------------------------------------------


def test_null_measurement_stays_null() -> None:
    (values,), rejections = validated(row(avgMoisture=None, avgColor=None, avgCombinedBd=None))

    assert rejections == []
    assert values["avg_moisture"] is None
    assert values["avg_color"] is None
    assert values["avg_combined_bd"] is None


def test_legitimate_zero_stays_zero() -> None:
    (values,), _ = validated(row(avgMoisture=0, avgColor=0.0, avgCombinedBd=0))

    assert values["avg_moisture"] == Decimal(0)
    assert values["avg_moisture"] is not None
    assert values["avg_color"] == Decimal(0)


def test_null_and_zero_are_different_rows() -> None:
    (null_row, zero_row), _ = validated(row(avgMoisture=None), row(avgMoisture=0))

    assert null_row["source_row_hash"] != zero_row["source_row_hash"]


def test_measurement_precision_is_exact() -> None:
    body = (
        b'[{"sourceDate": "2026-09-01", "campaignNo": "1", "lot": "L", "location": "S",'
        b' "product": "P", "avgMoisture": 0.1234567890123456789012345,'
        b' "avgColor": 0.43333333333333335, "avgCombinedBd": 1E+5}]'
    )
    (values,), _ = validate_rows(_parse_json(body), source_system="access", synced_at=SYNCED_AT)

    assert values["avg_moisture"] == Decimal("0.1234567890123456789012345")
    assert str(values["avg_moisture"]) == "0.1234567890123456789012345"
    assert values["avg_color"] == Decimal("0.43333333333333335")
    assert values["avg_combined_bd"] == Decimal("1E+5")


def test_raw_identifiers_and_locations_are_preserved() -> None:
    (values,), _ = validated(row(location="  SILO 1 ", product="prd-a", lot="", campaignNo=26101))

    assert values["location"] == "  SILO 1 "
    assert values["product"] == "prd-a"
    assert values["lot"] == ""
    assert values["campaign_no"] == "26101"


@pytest.mark.parametrize("value", [-5, 0.000001, 999999999, 1e10])
def test_unusual_measurements_are_not_rejected(value: float) -> None:
    accepted, rejections = validated(row(avgMoisture=value))

    assert rejections == []
    assert len(accepted) == 1


def test_values_carry_source_identity_and_sync_time() -> None:
    (values,), _ = validated(row())

    assert values["source_system"] == "access"
    assert values["synced_at"] == SYNCED_AT
    assert values["source_date"] == dt.date(2026, 9, 1)


# Deterministic hashing -------------------------------------------------------------


def test_hash_is_deterministic() -> None:
    (first,), _ = validated(row())
    (second,), _ = validated(row())

    assert first["source_row_hash"] == second["source_row_hash"]


def test_hash_ignores_json_key_order_and_number_spelling() -> None:
    reordered = dict(reversed(list(row().items())))
    (a, b, c), _ = validated(row(), reordered, row(avgColor=40, campaignNo=26101))

    assert a["source_row_hash"] == b["source_row_hash"] == c["source_row_hash"]


def test_hash_matches_the_source_field_hash() -> None:
    (values,), _ = validated(row())

    assert values["source_row_hash"] == compute_source_row_hash(
        {
            "DATE": "2026-09-01",
            "CAMPNO": "26101",
            "LOT": "A260901-01",
            "Location": "Silo 1",
            "PRODUCT": "PRD-A",
            "AvgOfMOISTURE": 0.4,
            "AvgOfCOLOR": 40.0,
            "AvgOfCombined_BD": 0.7,
        }
    )


def test_hash_changes_with_any_value() -> None:
    (base,), _ = validated(row())
    for field, value in {
        "sourceDate": "2026-09-02",
        "campaignNo": "26102",
        "lot": "other",
        "location": "SILO 1",
        "product": "PRD-B",
        "avgMoisture": 0.41,
        "avgColor": None,
        "avgCombinedBd": 0,
    }.items():
        (changed,), _ = validated(row(**{field: value}))
        assert changed["source_row_hash"] != base["source_row_hash"], field


def test_correct_client_hash_is_accepted() -> None:
    (values,), _ = validated(row())

    accepted, rejections = validated(row(sourceRowHash=values["source_row_hash"]))

    assert rejections == []
    assert accepted[0]["source_row_hash"] == values["source_row_hash"]


# Database failure ----------------------------------------------------------------


def test_database_failure_is_reported_separately_and_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unreachable = sessionmaker(
        bind=create_engine(UNREACHABLE_DB, connect_args={"connect_timeout": 2})
    )
    caplog.set_level(logging.INFO)
    with make_client(enabled_settings(), session_factory=unreachable) as client:
        response = client.post(URL, json=batch(row(lot="LOT-SHOULD-NOT-BE-LOGGED")))

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "database_unavailable"
    assert detail["batchId"] == "batch-0001"
    assert "not-a-real-password" not in response.text
    assert "result=database_error" in caplog.text
    assert "error_type=OperationalError" in caplog.text
    assert "not-a-real-password" not in caplog.text
    assert "LOT-SHOULD-NOT-BE-LOGGED" not in caplog.text


# Logging -----------------------------------------------------------------------------


def test_batch_outcome_is_logged_without_row_values(
    enabled: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    enabled.post(
        URL,
        json=batch(row(sourceDate="bad", lot="LOT-SHOULD-NOT-BE-LOGGED"), row(avgColor="x")),
        headers={"authorization": "Bearer header-should-not-be-logged"},
    )

    (record,) = [r for r in caplog.records if "event=finishing_ingestion" in r.getMessage()]
    message = record.getMessage()
    for expected in (
        "result=rejected",
        "batch_id=batch-0001",
        "source_system=access-qryFINISHING-AVG",
        "received=2",
        "inserted=0",
        "duplicates=0",
        "rejected=2",
        "rejected_fields=avgColor:1,sourceDate:1",
    ):
        assert expected in message
    assert record.ingestion["rejected"] == 2
    assert "LOT-SHOULD-NOT-BE-LOGGED" not in caplog.text
    assert "header-should-not-be-logged" not in caplog.text


def test_unknown_field_names_are_not_logged_verbatim(
    enabled: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    enabled.post(URL, json=batch(row(**{"injected field": 1})))

    assert "injected field" not in caplog.text
    assert "rejected_fields=other:1" in caplog.text
