"""Test doubles and builders. No Access, ODBC driver, Credential Manager, or API."""

import datetime as dt
import io
import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from access_finishing_sync.config import Config, load_config
from access_finishing_sync.credentials import Secret
from access_finishing_sync.logs import Redactor, RunLogger, configure_logging
from access_finishing_sync.odbc import EXPECTED_COLUMNS, Extraction, ProbeResult
from access_finishing_sync.service import SyncService
from access_finishing_sync.transport import HttpResponse, TransportError
from access_finishing_sync.window import DateWindow

# Deliberately not in the opc_ format, so redaction of the registered secret
# itself (not just the token pattern) is exercised.
SECRET = "TestOnlySecretValue-7f3a9c1e5b"
TODAY = dt.date(2026, 10, 2)
NOW = dt.datetime(2026, 10, 2, 17, 40, 0, tzinfo=dt.UTC)
DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"


def base_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        "API_BASE_URL": "https://ops.example.test",
        "ACCESS_DATABASE_PATH": str(tmp_path / "source" / "Finishing.accdb"),
        "ACCESS_ODBC_DRIVER": DRIVER,
        "LOG_DIRECTORY": str(tmp_path / "logs"),
        "LOCK_DIRECTORY": str(tmp_path / "locks"),
    }
    env.update(overrides)
    return env


def make_config(tmp_path: Path, **overrides: str) -> Config:
    return load_config(base_env(tmp_path, **overrides))


def source_row(
    day: Any = dt.date(2026, 10, 1),
    campno: Any = "26101",
    lot: Any = "A260901-01",
    location: Any = "Silo 1",
    product: Any = "PRD-A",
    moisture: Any = Decimal("0.4"),
    color: Any = Decimal("40"),
    bulk_density: Any = Decimal("0.7"),
) -> tuple[Any, ...]:
    return (day, campno, lot, location, product, moisture, color, bulk_density)


class Forbidden:
    """A factory that must never be called."""

    def __init__(self, what: str) -> None:
        self.what = what

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{self.what} must not be used")


class FakeCredentials:
    description = "test credential provider"

    def __init__(self, value: str = SECRET, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls = 0

    def get_secret(self) -> Secret:
        self.calls += 1
        if self.error:
            raise self.error
        return Secret(self.value)


class FakeRepository:
    def __init__(
        self,
        rows: Sequence[tuple[Any, ...]] = (),
        probe_result: ProbeResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.rows = list(rows)
        self.probe_result = probe_result or ProbeResult(
            python_architecture="64-bit",
            columns=EXPECTED_COLUMNS,
            missing_columns=(),
            row_retrieved=True,
            readonly_attribute=True,
        )
        self.error = error
        self.windows: list[DateWindow] = []
        self.probes = 0

    def probe(self) -> ProbeResult:
        self.probes += 1
        if self.error:
            raise self.error
        return self.probe_result

    def extract(self, window: DateWindow) -> Extraction:
        self.windows.append(window)
        if self.error:
            raise self.error
        return Extraction(rows=list(self.rows), readonly_attribute=True)


Reply = HttpResponse | TransportError | Callable[[bytes], HttpResponse]


class FakeTransport:
    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self.closed = False

    def post(self, url: str, body: bytes, headers: Any) -> HttpResponse:
        self.calls.append((url, body, dict(headers)))
        reply = self.replies.pop(0)
        if isinstance(reply, TransportError):
            raise reply
        if callable(reply):
            return reply(body)
        return reply

    def close(self) -> None:
        self.closed = True


class FakeLock:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> "FakeLock":
        if self.error:
            raise self.error
        self.entered += 1
        return self

    def __exit__(self, *args: object) -> None:
        self.exited += 1


def result_for(
    body: bytes,
    *,
    rejected: Sequence[int] = (),
    replayed: bool = False,
    duplicates: int = 0,
    superseded: int = 0,
    restored: int = 0,
    **overrides: Any,
) -> dict[str, Any]:
    """A consistent server result for the request body."""
    request = json.loads(body)
    received = len(request["rows"])
    inserted = received - len(rejected) - duplicates - restored
    document = {
        "batchId": request["batchId"],
        "sourceSystem": request["sourceSystem"],
        "status": "accepted"
        if not rejected
        else ("accepted_with_rejections" if received > len(rejected) else "rejected"),
        "receivedRows": received,
        "insertedRows": inserted,
        "duplicateRows": duplicates,
        "rejectedRows": len(rejected),
        "restoredRows": restored,
        "supersededRows": superseded,
        "windowApplied": not rejected,
        "replayed": replayed,
        "rejections": [
            {
                "rowIndex": i,
                "errors": [{"field": "avgMoisture", "message": "must be a JSON number or null"}],
            }
            for i in rejected
        ],
        "rejectionsTruncated": False,
    }
    document.update(overrides)
    return document


def ok(**kwargs: Any) -> Callable[[bytes], HttpResponse]:
    def reply(body: bytes) -> HttpResponse:
        return HttpResponse(200, {}, json.dumps(result_for(body, **kwargs)).encode())

    return reply


def error_response(status: int, code: str, message: str = "x", **headers: str) -> HttpResponse:
    body = json.dumps({"detail": {"error": code, "message": message}}).encode()
    return HttpResponse(status, {k.lower().replace("_", "-"): v for k, v in headers.items()}, body)


class LogCapture:
    def __init__(self) -> None:
        self.stream = io.StringIO()
        self.redactor = Redactor()
        self.logger = configure_logging(self.redactor, stream=self.stream)
        self.log = RunLogger(self.logger, run_id="test-run")

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    @property
    def events(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.text.splitlines() if line.strip()]

    def named(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]


class Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_service(
    config: Config,
    capture: LogCapture,
    *,
    repository: Any = None,
    transport: Any = None,
    credentials: Any = None,
    lock: Any = None,
    sleep: Sleeper | None = None,
) -> SyncService:
    def factory(value: Any, what: str) -> Callable[[], Any]:
        if value is None:
            return Forbidden(what)
        if isinstance(value, Forbidden):
            return value
        return lambda: value

    return SyncService(
        config,
        log=capture.log,
        redactor=capture.redactor,
        credential_provider_factory=factory(credentials, "credential provider"),
        repository_factory=factory(repository, "Access repository"),
        transport_factory=factory(transport, "HTTP transport"),
        lock_factory=factory(lock if lock is not None else FakeLock(), "lock"),
        today=lambda: TODAY,
        now=lambda: NOW,
        sleep=sleep or Sleeper(),
        jitter=lambda: 0.5,
    )
