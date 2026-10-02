import datetime as dt
import json
import re
import uuid
from decimal import Decimal

import pytest
from support import NOW

from access_finishing_sync import payload as payload_module
from access_finishing_sync.errors import ExitCode, ExtractionError
from access_finishing_sync.payload import (
    build_payload,
    new_batch_id,
    prepare_request,
    serialize,
)
from access_finishing_sync.window import calculate_window

WINDOW = calculate_window(dt.date(2026, 10, 2), 60)
API_NAME_RULE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,99}")


def api_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sourceDate": "2026-10-01",
        "campaignNo": "00261",
        "lot": "A1",
        "location": " Silo 1 ",
        "product": "PRD-A",
        "avgMoisture": Decimal("0.4"),
        "avgColor": None,
        "avgCombinedBd": Decimal("0"),
    }
    row.update(overrides)
    return row


def prepare(rows: list[dict[str, object]] | None = None, batch_id: str = "b-1"):
    return prepare_request(
        source_system="access-qryFINISHING-AVG",
        batch_id=batch_id,
        extracted_at=NOW,
        window=WINDOW,
        rows=rows if rows is not None else [api_row()],
    )


def test_batch_id_contains_source_connector_timestamp_and_uuid() -> None:
    fixed = uuid.UUID("12345678123456781234567812345678")

    batch_id = new_batch_id("access-qryFINISHING-AVG", "lcy-access-sync", NOW, lambda: fixed)

    assert batch_id == (
        "access-qryFINISHING-AVG:lcy-access-sync:20261002T174000Z:12345678123456781234567812345678"
    )
    assert API_NAME_RULE.fullmatch(batch_id)


def test_batch_ids_are_unique_per_extraction() -> None:
    ids = {new_batch_id("s", "c", NOW) for _ in range(100)}

    assert len(ids) == 100


def test_batch_id_timestamp_is_utc() -> None:
    local = dt.datetime(2026, 10, 2, 12, 40, tzinfo=dt.timezone(dt.timedelta(hours=-5)))

    assert ":20261002T174000Z:" in new_batch_id("s", "c", local)


def test_payload_declares_the_inclusive_window_and_extraction_time() -> None:
    document = json.loads(prepare().body)

    assert document["sourceSystem"] == "access-qryFINISHING-AVG"
    assert document["batchId"] == "b-1"
    assert document["extractedAt"] == "2026-10-02T17:40:00+00:00"
    assert document["reconciliationWindow"] == {
        "sourceDateFrom": "2026-08-04",
        "sourceDateTo": "2026-10-02",
    }
    assert "sourceRecordId" not in document["rows"][0]


def test_extracted_at_requires_a_time_zone() -> None:
    with pytest.raises(ValueError):
        build_payload(
            source_system="s",
            batch_id="b",
            extracted_at=dt.datetime(2026, 10, 2, 12, 0),
            window=WINDOW,
            rows=[api_row()],
        )


def test_serialization_is_deterministic() -> None:
    first = prepare([api_row(), api_row(lot="A2")])
    second = prepare([api_row(), api_row(lot="A2")])

    assert first.body == second.body
    assert first.body_sha256 == second.body_sha256


def test_decimals_are_written_as_exact_json_numbers() -> None:
    body = prepare(
        [api_row(avgMoisture=Decimal("0.1234567890123456789012345"), avgColor=Decimal("40.10"))]
    ).body

    assert b'"avgMoisture":0.1234567890123456789012345' in body
    assert b'"avgColor":40.10' in body
    parsed = json.loads(body, parse_float=Decimal)
    assert parsed["rows"][0]["avgMoisture"] == Decimal("0.1234567890123456789012345")


def test_null_and_zero_are_serialized_distinctly() -> None:
    body = prepare([api_row(avgColor=None, avgCombinedBd=Decimal("0"))]).body

    assert b'"avgColor":null' in body
    assert b'"avgCombinedBd":0' in body


@pytest.mark.parametrize(
    "value", [Decimal("1E-7"), Decimal("-0"), Decimal("1E+3"), Decimal("0E-7")]
)
def test_exponent_forms_are_valid_json(value: Decimal) -> None:
    body = serialize({"v": value})

    assert json.loads(body, parse_float=Decimal)["v"] == value


def test_floats_are_never_serialized() -> None:
    with pytest.raises(TypeError):
        serialize({"v": 0.1})


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_numbers_are_never_serialized(value: Decimal) -> None:
    with pytest.raises(ValueError):
        serialize({"v": value})


def test_identifiers_are_serialized_as_strings_exactly() -> None:
    body = prepare([api_row(campaignNo="00261", location="  Sílo\t1 ")]).body

    row = json.loads(body)["rows"][0]
    assert row["campaignNo"] == "00261"
    assert row["location"] == "  Sílo\t1 "
    assert body.isascii()


def test_oversized_body_fails_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payload_module, "MAX_BODY_BYTES", 100)

    with pytest.raises(ExtractionError) as caught:
        prepare()

    assert caught.value.reason == "window_too_large"
    assert caught.value.exit_code == ExitCode.EXTRACTION
