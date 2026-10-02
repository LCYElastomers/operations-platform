import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
from support import (
    SECRET,
    FakeCredentials,
    FakeLock,
    FakeRepository,
    FakeTransport,
    Forbidden,
    LogCapture,
    error_response,
    make_config,
    make_service,
    ok,
    source_row,
)

from access_finishing_sync.credentials import CredentialError
from access_finishing_sync.errors import ExitCode, LockActiveError, OdbcUnavailableError
from access_finishing_sync.odbc import ProbeResult
from access_finishing_sync.transport import TransportError
from access_finishing_sync.window import DateWindow

ROWS = [
    source_row(day=dt.date(2026, 9, 1), lot="LOT-VALUE-ONE", moisture=Decimal("0.987654321")),
    source_row(day=dt.date(2026, 9, 2), lot="LOT-VALUE-TWO", moisture=None),
    source_row(day=dt.datetime(2026, 10, 2, 0, 0), lot="LOT-VALUE-THREE", moisture=0.0),
]


def run(tmp_path: Path, action: str = "run-once", **kwargs) -> tuple[ExitCode, LogCapture]:
    capture = LogCapture()
    config = make_config(tmp_path, **kwargs.pop("env", {}))
    code = make_service(config, capture, **kwargs).execute(action)
    return code, capture


def finished(capture: LogCapture) -> dict:
    (event,) = capture.named("run_finished")
    return event


def assert_no_sensitive_output(capture: LogCapture) -> None:
    assert SECRET not in capture.text
    assert "Bearer" not in capture.text
    assert "LOT-VALUE" not in capture.text
    assert "0.987654321" not in capture.text
    assert '"rows":' not in capture.text


# run-once ---------------------------------------------------------------------------


def test_run_once_submits_the_complete_authoritative_window(tmp_path: Path) -> None:
    repository = FakeRepository(ROWS)
    transport = FakeTransport(ok(duplicates=1, superseded=2))
    credentials = FakeCredentials()

    code, capture = run(
        tmp_path, repository=repository, transport=transport, credentials=credentials
    )

    assert code == ExitCode.SUCCESS
    assert repository.windows == [DateWindow(dt.date(2026, 8, 4), dt.date(2026, 10, 2))]
    ((url, body, headers),) = transport.calls
    assert url.endswith("/api/v1/ingestion/quality/finishing/batches")
    assert headers["X-Connector-Id"] == "lcy-access-sync"
    assert headers["Authorization"] == f"Bearer {SECRET}"
    document = json.loads(body, parse_float=Decimal)
    assert document["sourceSystem"] == "access-qryFINISHING-AVG"
    assert document["reconciliationWindow"] == {
        "sourceDateFrom": "2026-08-04",
        "sourceDateTo": "2026-10-02",
    }
    assert [r["lot"] for r in document["rows"]] == [
        "LOT-VALUE-ONE",
        "LOT-VALUE-TWO",
        "LOT-VALUE-THREE",
    ]
    assert [r["avgMoisture"] for r in document["rows"]] == [Decimal("0.987654321"), None, 0]
    assert transport.closed

    (result,) = capture.named("submission_result")
    assert {k: result[k] for k in result if k.endswith("_rows")} == {
        "received_rows": 3,
        "inserted_rows": 2,
        "duplicate_rows": 1,
        "rejected_rows": 0,
        "superseded_rows": 2,
        "restored_rows": 0,
    }
    assert result["replayed"] is False
    assert result["batch_id"] == document["batchId"]
    assert finished(capture)["status"] == "success"
    assert capture.named("extraction_finished")[0]["extracted_rows"] == 3
    assert capture.named("window_calculated")[0]["query_upper_bound_exclusive"] == "2026-10-03"
    assert {e["phase"] for e in capture.named("phase_finished")} == {"extract", "map", "submit"}
    assert_no_sensitive_output(capture)


def test_every_log_event_carries_the_connector_identity(tmp_path: Path) -> None:
    capture = LogCapture()
    capture.log.context.update(connector_id="lcy-access-sync", source_system="src")
    config = make_config(tmp_path)
    service = make_service(
        config,
        capture,
        repository=FakeRepository(ROWS),
        transport=FakeTransport(ok()),
        credentials=FakeCredentials(),
    )

    service.execute("run-once")

    assert all(e["connector_id"] == "lcy-access-sync" for e in capture.events)


def test_empty_extraction_is_never_submitted(tmp_path: Path) -> None:
    code, capture = run(
        tmp_path,
        repository=FakeRepository([]),
        transport=Forbidden("HTTP transport"),
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.EXTRACTION
    assert capture.named("run_error")[0]["reason"] == "empty_window"
    assert finished(capture)["status"] == "attention_required"


def test_window_above_batch_size_is_never_submitted(tmp_path: Path) -> None:
    rows = [source_row(lot=f"L{i}") for i in range(4)]

    code, capture = run(
        tmp_path,
        env={"BATCH_SIZE": "3"},
        repository=FakeRepository(rows),
        transport=Forbidden("HTTP transport"),
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.EXTRACTION
    (error,) = capture.named("run_error")
    assert (error["reason"], error["extracted_rows"], error["batch_size"]) == (
        "window_too_large",
        4,
        3,
    )
    assert "Reduce RECONCILIATION_DAYS" in error["message"]
    assert finished(capture)["status"] == "attention_required"


def test_window_above_the_api_maximum_is_never_split(tmp_path: Path) -> None:
    rows = [source_row(lot=f"L{i}") for i in range(5001)]

    code, capture = run(
        tmp_path,
        repository=FakeRepository(rows),
        transport=Forbidden("HTTP transport"),
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.EXTRACTION
    assert capture.named("run_error")[0]["extracted_rows"] == 5001


def test_window_at_the_api_maximum_is_sent_as_one_request(tmp_path: Path) -> None:
    transport = FakeTransport(ok())

    code, _ = run(
        tmp_path,
        repository=FakeRepository([source_row(lot=f"L{i}") for i in range(5000)]),
        transport=transport,
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.SUCCESS
    assert len(transport.calls) == 1
    assert len(json.loads(transport.calls[0][1])["rows"]) == 5000


def test_locally_invalid_rows_prevent_any_submission(tmp_path: Path) -> None:
    rows = [*ROWS, source_row(day="2026-09-03", moisture=float("nan"))]

    code, capture = run(
        tmp_path,
        repository=FakeRepository(rows),
        transport=Forbidden("HTTP transport"),
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.EXTRACTION
    assert [(e["row_index"], e["field"]) for e in capture.named("row_invalid")] == [
        (3, "DATE"),
        (3, "AvgOfMOISTURE"),
    ]
    assert capture.named("run_error")[0]["reason"] == "local_validation_failed"
    assert "2026-09-03" not in capture.text
    assert_no_sensitive_output(capture)


def test_partial_acceptance_is_attention_required(tmp_path: Path) -> None:
    code, capture = run(
        tmp_path,
        repository=FakeRepository(ROWS),
        transport=FakeTransport(ok(rejected=[1])),
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.PARTIAL_ACCEPTANCE
    (rejected,) = capture.named("row_rejected")
    assert rejected["row_index"] == 1
    assert rejected["errors"] == [
        {"field": "avgMoisture", "reason": "must be a JSON number or null"}
    ]
    assert capture.named("partial_acceptance")[0]["window_applied"] is False
    assert finished(capture)["status"] == "attention_required"
    assert_no_sensitive_output(capture)


def test_retries_reuse_the_batch_id_and_bytes(tmp_path: Path) -> None:
    transport = FakeTransport(
        TransportError("timeout", "ReadTimeout"), error_response(503, "busy"), ok(replayed=True)
    )

    code, capture = run(
        tmp_path,
        repository=FakeRepository(ROWS),
        transport=transport,
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.SUCCESS
    bodies = [body for _, body, _ in transport.calls]
    assert len(bodies) == 3
    assert bodies[0] == bodies[1] == bodies[2]
    assert len({json.loads(b)["batchId"] for b in bodies}) == 1
    assert capture.named("submission_result")[0]["replayed"] is True


def test_each_run_uses_a_new_batch_id(tmp_path: Path) -> None:
    first, second = FakeTransport(ok()), FakeTransport(ok())

    for transport in (first, second):
        run(
            tmp_path,
            repository=FakeRepository(ROWS),
            transport=transport,
            credentials=FakeCredentials(),
        )

    assert json.loads(first.calls[0][1])["batchId"] != json.loads(second.calls[0][1])["batchId"]


@pytest.mark.parametrize(
    ("response", "exit_code", "status"),
    [
        (error_response(401, "invalid_credentials"), ExitCode.AUTHENTICATION, "failed"),
        (error_response(403, "source_system_not_allowed"), ExitCode.AUTHENTICATION, "failed"),
        (error_response(409, "stale_batch"), ExitCode.API_REJECTED, "attention_required"),
        (error_response(409, "batch_id_conflict"), ExitCode.API_REJECTED, "attention_required"),
        (error_response(413, "payload_too_large"), ExitCode.API_REJECTED, "failed"),
    ],
)
def test_permanent_api_failures(tmp_path: Path, response, exit_code: ExitCode, status: str) -> None:
    transport = FakeTransport(response)

    code, capture = run(
        tmp_path,
        repository=FakeRepository(ROWS),
        transport=transport,
        credentials=FakeCredentials(),
    )

    assert code == exit_code
    assert len(transport.calls) == 1
    assert finished(capture)["status"] == status
    assert_no_sensitive_output(capture)


def test_transient_failure_after_retries(tmp_path: Path) -> None:
    transport = FakeTransport(*[TransportError("connect", "ConnectError")] * 2)

    code, capture = run(
        tmp_path,
        env={"HTTP_MAX_ATTEMPTS": "2"},
        repository=FakeRepository(ROWS),
        transport=transport,
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.TRANSIENT
    assert len(transport.calls) == 2


def test_missing_secret_stops_before_extraction(tmp_path: Path) -> None:
    code, capture = run(
        tmp_path,
        repository=Forbidden("Access repository"),
        transport=Forbidden("HTTP transport"),
        credentials=FakeCredentials(error=CredentialError("No connector secret found.")),
    )

    assert code == ExitCode.CONFIGURATION


def test_active_lock_stops_the_run(tmp_path: Path) -> None:
    code, capture = run(
        tmp_path,
        repository=Forbidden("Access repository"),
        transport=Forbidden("HTTP transport"),
        credentials=Forbidden("credential provider"),
        lock=FakeLock(LockActiveError("Another run is active.", reason="lock_active")),
    )

    assert code == ExitCode.LOCK_ACTIVE


def test_lock_is_held_during_the_run_and_released(tmp_path: Path) -> None:
    lock = FakeLock()

    run(
        tmp_path,
        repository=FakeRepository(ROWS),
        transport=FakeTransport(ok()),
        credentials=FakeCredentials(),
        lock=lock,
    )

    assert (lock.entered, lock.exited) == (1, 1)


def test_odbc_failure_during_run(tmp_path: Path) -> None:
    error = OdbcUnavailableError("driver missing", reason="driver_not_found")

    code, _ = run(
        tmp_path,
        repository=FakeRepository(error=error),
        transport=Forbidden("HTTP transport"),
        credentials=FakeCredentials(),
    )

    assert code == ExitCode.ODBC_UNAVAILABLE


# dry-run ----------------------------------------------------------------------------


def test_dry_run_extracts_and_validates_without_submitting(tmp_path: Path) -> None:
    repository = FakeRepository(ROWS)

    code, capture = run(
        tmp_path,
        "dry-run",
        repository=repository,
        transport=Forbidden("HTTP transport"),
        credentials=Forbidden("credential provider"),
    )

    assert code == ExitCode.SUCCESS
    assert len(repository.windows) == 1
    (done,) = capture.named("dry_run_complete")
    assert (done["row_count"], done["submitted"]) == (3, False)
    assert not any(tmp_path.iterdir())  # nothing written to disk
    assert_no_sensitive_output(capture)


def test_dry_run_reports_validation_failures(tmp_path: Path) -> None:
    code, capture = run(
        tmp_path,
        "dry-run",
        repository=FakeRepository([source_row(color=float("inf"))]),
        transport=Forbidden("HTTP transport"),
    )

    assert code == ExitCode.EXTRACTION
    assert capture.named("row_invalid")[0]["field"] == "AvgOfCOLOR"


def test_dry_run_applies_the_same_fail_safes(tmp_path: Path) -> None:
    code, _ = run(
        tmp_path, "dry-run", repository=FakeRepository([]), transport=Forbidden("HTTP transport")
    )

    assert code == ExitCode.EXTRACTION


# check-config / check-odbc ----------------------------------------------------------


def test_check_config_only_touches_configuration_and_credentials(tmp_path: Path) -> None:
    credentials = FakeCredentials()

    code, capture = run(
        tmp_path,
        "check-config",
        repository=Forbidden("Access repository"),
        transport=Forbidden("HTTP transport"),
        credentials=credentials,
        lock=Forbidden("lock"),
    )

    assert code == ExitCode.SUCCESS
    assert credentials.calls == 1
    assert capture.named("configuration_valid")[0]["secret_available"] is True
    assert SECRET not in capture.text
    assert not any(tmp_path.iterdir())


def test_check_config_reports_a_missing_secret(tmp_path: Path) -> None:
    code, capture = run(
        tmp_path,
        "check-config",
        credentials=FakeCredentials(error=CredentialError("No connector secret found.")),
        lock=Forbidden("lock"),
    )

    assert code == ExitCode.CONFIGURATION
    assert finished(capture)["status"] == "failed"


def test_check_odbc_never_uses_http_or_credentials(tmp_path: Path) -> None:
    repository = FakeRepository()

    code, capture = run(
        tmp_path,
        "check-odbc",
        repository=repository,
        transport=Forbidden("HTTP transport"),
        credentials=Forbidden("credential provider"),
        lock=Forbidden("lock"),
    )

    assert code == ExitCode.SUCCESS
    assert repository.probes == 1
    assert repository.windows == []
    probe = capture.named("odbc_probe")[0]
    assert (probe["column_count"], probe["missing_columns"]) == (8, [])


def test_check_odbc_reports_missing_columns(tmp_path: Path) -> None:
    probe = ProbeResult("64-bit", ("DATE", "LOT"), ("CAMPNO", "Location"), False, True)

    code, capture = run(
        tmp_path,
        "check-odbc",
        repository=FakeRepository(probe_result=probe),
        transport=Forbidden("HTTP transport"),
    )

    assert code == ExitCode.ODBC_UNAVAILABLE
    assert capture.named("run_error")[0]["missing_columns"] == ["CAMPNO", "Location"]


def test_check_odbc_reports_driver_problems(tmp_path: Path) -> None:
    error = OdbcUnavailableError("not available to this 64-bit Python", reason="driver_not_found")

    code, capture = run(
        tmp_path,
        "check-odbc",
        repository=FakeRepository(error=error),
        transport=Forbidden("HTTP transport"),
    )

    assert code == ExitCode.ODBC_UNAVAILABLE
    assert "64-bit" in capture.named("run_error")[0]["message"]
