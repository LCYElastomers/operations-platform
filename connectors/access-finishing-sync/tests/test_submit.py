import datetime as dt
import json
from decimal import Decimal
from typing import Any

import pytest
from support import NOW, SECRET, FakeTransport, LogCapture, Sleeper, error_response, ok, result_for

from access_finishing_sync.errors import (
    ApiRejectedError,
    AuthenticationError,
    ExitCode,
    TransientFailureError,
    UnexpectedResponseError,
)
from access_finishing_sync.payload import PreparedRequest, prepare_request
from access_finishing_sync.retry import RetryPolicy
from access_finishing_sync.submit import Submitter
from access_finishing_sync.transport import HttpResponse, TransportError
from access_finishing_sync.window import calculate_window

URL = "https://ops.example.test/api/v1/ingestion/quality/finishing/batches"
SOURCE = "access-qryFINISHING-AVG"


def request(rows: int = 3) -> PreparedRequest:
    return prepare_request(
        source_system=SOURCE,
        batch_id="access-qryFINISHING-AVG:lcy-access-sync:20261002T174000Z:abc",
        extracted_at=NOW,
        window=calculate_window(dt.date(2026, 10, 2), 60),
        rows=[
            {
                "sourceDate": "2026-10-01",
                "campaignNo": "26101",
                "lot": f"LOT-VALUE-{i}",
                "location": "Silo 1",
                "product": "PRD-A",
                "avgMoisture": Decimal("0.987654321"),
                "avgColor": None,
                "avgCombinedBd": Decimal("0"),
            }
            for i in range(rows)
        ],
    )


def submitter(
    transport: FakeTransport, capture: LogCapture, sleeper: Sleeper | None = None, attempts: int = 5
) -> Submitter:
    return Submitter(
        url=URL,
        connector_id="lcy-access-sync",
        source_system=SOURCE,
        transport=transport,
        policy=RetryPolicy(max_attempts=attempts),
        log=capture.log,
        sleep=sleeper or Sleeper(),
        jitter=lambda: 0.0,
        now=lambda: NOW,
    )


def test_request_is_authenticated_and_json() -> None:
    transport = FakeTransport(ok())

    outcome = submitter(transport, LogCapture()).submit(request(), SECRET)

    url, body, headers = transport.calls[0]
    assert url == URL
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Connector-Id"] == "lcy-access-sync"
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert (outcome.received_rows, outcome.inserted_rows, outcome.window_applied) == (3, 3, True)


def test_transient_failures_are_retried_with_identical_bytes() -> None:
    prepared = request()
    transport = FakeTransport(
        error_response(503, "database_unavailable"),
        TransportError("timeout", "ReadTimeout"),
        TransportError("connect", "ConnectError"),
        error_response(502, "bad_gateway"),
        ok(replayed=True),
    )
    sleeper = Sleeper()

    outcome = submitter(transport, LogCapture(), sleeper).submit(prepared, SECRET)

    bodies = [body for _, body, _ in transport.calls]
    assert len(bodies) == 5
    assert all(body is prepared.body for body in bodies)
    assert {json.loads(body)["batchId"] for body in bodies} == {prepared.batch_id}
    assert {json.loads(body)["extractedAt"] for body in bodies} == {prepared.extracted_at}
    assert outcome.replayed is True
    assert sleeper.delays == [1, 2, 4, 8]


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_each_transient_status_is_retried(status: int) -> None:
    transport = FakeTransport(error_response(status, "busy"), ok())

    submitter(transport, LogCapture()).submit(request(), SECRET)

    assert len(transport.calls) == 2


def test_retry_after_is_honoured() -> None:
    transport = FakeTransport(error_response(429, "too_many", Retry_After="7"), ok())
    sleeper = Sleeper()

    submitter(transport, LogCapture(), sleeper).submit(request(), SECRET)

    assert sleeper.delays == [7]


def test_retry_after_is_capped() -> None:
    transport = FakeTransport(error_response(503, "busy", Retry_After="86400"), ok())
    sleeper = Sleeper()

    submitter(transport, LogCapture(), sleeper).submit(request(), SECRET)

    assert sleeper.delays == [120]


def test_retries_are_bounded() -> None:
    transport = FakeTransport(*[TransportError("connect", "ConnectError")] * 3)
    sleeper = Sleeper()

    with pytest.raises(TransientFailureError) as caught:
        submitter(transport, LogCapture(), sleeper, attempts=3).submit(request(), SECRET)

    assert len(transport.calls) == 3
    assert len(sleeper.delays) == 2
    assert caught.value.exit_code == ExitCode.TRANSIENT
    assert caught.value.fields["last_outcome"] == "network_connect"


@pytest.mark.parametrize(
    ("response", "error_type", "reason", "exit_code"),
    [
        (error_response(401, "invalid_credentials"), AuthenticationError, "invalid_credentials", 6),
        (
            error_response(403, "source_system_not_allowed"),
            AuthenticationError,
            "source_system_not_allowed",
            6,
        ),
        (error_response(409, "stale_batch"), ApiRejectedError, "stale_batch", 7),
        (error_response(409, "batch_id_conflict"), ApiRejectedError, "batch_id_conflict", 7),
        (error_response(413, "payload_too_large"), ApiRejectedError, "payload_too_large", 7),
        (error_response(400, "invalid_json"), ApiRejectedError, "invalid_json", 7),
        (
            error_response(415, "unsupported_media_type"),
            ApiRejectedError,
            "unsupported_media_type",
            7,
        ),
        (error_response(422, "validation_error"), ApiRejectedError, "validation_error", 7),
        (HttpResponse(404, {}, b"not found"), ApiRejectedError, "http_404", 7),
        (HttpResponse(500, {}, b"boom"), UnexpectedResponseError, "http_500", 10),
    ],
)
def test_permanent_failures_are_not_retried(
    response: HttpResponse, error_type: type, reason: str, exit_code: int
) -> None:
    transport = FakeTransport(response)
    sleeper = Sleeper()

    with pytest.raises(error_type) as caught:
        submitter(transport, LogCapture(), sleeper).submit(request(), SECRET)

    assert len(transport.calls) == 1
    assert sleeper.delays == []
    assert caught.value.reason == reason
    assert caught.value.exit_code == exit_code


def test_validation_failure_reports_field_names_only() -> None:
    body = json.dumps(
        {
            "detail": {
                "error": "validation_error",
                "message": "Request body is invalid.",
                "errors": [{"field": "extractedAt", "message": "LEAKED-VALUE-123"}],
            }
        }
    ).encode()
    capture = LogCapture()

    with pytest.raises(ApiRejectedError) as caught:
        submitter(FakeTransport(HttpResponse(422, {}, body)), capture).submit(request(), SECRET)

    assert caught.value.fields["invalid_fields"] == ["extractedAt"]
    assert "LEAKED-VALUE-123" not in capture.text


def test_server_error_messages_are_not_logged() -> None:
    capture = LogCapture()
    response = error_response(503, "database_unavailable", message="SQL internals: password=x")

    with pytest.raises(TransientFailureError):
        submitter(FakeTransport(response), capture, attempts=1).submit(request(), SECRET)

    assert "SQL internals" not in capture.text


def test_partial_acceptance_is_parsed() -> None:
    outcome = submitter(FakeTransport(ok(rejected=[1])), LogCapture()).submit(request(), SECRET)

    assert (outcome.status, outcome.rejected_rows, outcome.window_applied) == (
        "accepted_with_rejections",
        1,
        False,
    )
    assert outcome.rejections[0].row_index == 1
    assert outcome.rejections[0].errors == (("avgMoisture", "must be a JSON number or null"),)


def respond_with(**overrides: Any):
    def reply(body: bytes) -> HttpResponse:
        return HttpResponse(200, {}, json.dumps(result_for(body, **overrides)).encode())

    return reply


@pytest.mark.parametrize(
    "overrides",
    [
        {"insertedRows": 2},  # counts do not add up
        {"receivedRows": 4, "insertedRows": 4},  # not the number of rows sent
        {"batchId": "other"},
        {"sourceSystem": "other"},
        {"status": "rejected"},
        {"status": "unknown"},
        {"windowApplied": False},
        {"windowApplied": None},
        {"replayed": "no"},
        {"insertedRows": -1, "duplicateRows": 4},
        {"insertedRows": True},
        {"rejections": [{"rowIndex": 0, "errors": []}]},
    ],
)
def test_inconsistent_results_are_unexpected(overrides: dict[str, Any]) -> None:
    with pytest.raises(UnexpectedResponseError) as caught:
        submitter(FakeTransport(respond_with(**overrides)), LogCapture()).submit(request(), SECRET)

    assert caught.value.exit_code == ExitCode.INTERNAL


@pytest.mark.parametrize(
    "rejections",
    [
        [{"rowIndex": 3, "errors": []}],  # out of range
        [{"rowIndex": 0, "errors": []}, {"rowIndex": 0, "errors": []}],
        [],
    ],
)
def test_inconsistent_rejections_are_unexpected(rejections: list[dict[str, Any]]) -> None:
    reply = respond_with(rejected=[0], rejections=rejections)

    with pytest.raises(UnexpectedResponseError):
        submitter(FakeTransport(reply), LogCapture()).submit(request(), SECRET)


def test_truncated_rejections_are_accepted() -> None:
    reply = respond_with(
        rejected=[0, 1, 2],
        rejections=[{"rowIndex": 0, "errors": []}],
        rejectionsTruncated=True,
    )

    outcome = submitter(FakeTransport(reply), LogCapture()).submit(request(), SECRET)

    assert (outcome.rejected_rows, len(outcome.rejections)) == (3, 1)


def test_non_json_success_is_unexpected() -> None:
    with pytest.raises(UnexpectedResponseError):
        submitter(FakeTransport(HttpResponse(200, {}, b"<html>")), LogCapture()).submit(
            request(), SECRET
        )


def test_submission_logs_contain_no_secret_body_or_values() -> None:
    capture = LogCapture()
    capture.redactor.add(SECRET)

    submitter(FakeTransport(error_response(503, "busy"), ok()), capture).submit(request(), SECRET)

    assert SECRET not in capture.text
    assert "Bearer" not in capture.text
    assert "LOT-VALUE" not in capture.text
    assert "0.987654321" not in capture.text
    assert '"rows"' not in capture.text
