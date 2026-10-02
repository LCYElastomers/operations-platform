"""Orchestration of the four operating actions.

Run-once pipeline: lock -> secret -> window -> Access extraction -> local
mapping/validation -> fail-safe checks -> one serialized request -> submission
with retries -> response validation. A reconciliation window is declared only
when the whole window was extracted and validated and fits one request.
"""

import datetime as dt
import random
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Literal

from access_finishing_sync.config import MAX_SERVER_BATCH_ROWS, Config
from access_finishing_sync.credentials import CredentialProvider
from access_finishing_sync.errors import (
    ConnectorError,
    ExitCode,
    ExtractionError,
    OdbcUnavailableError,
)
from access_finishing_sync.logs import Redactor, RunLogger
from access_finishing_sync.mapping import map_rows
from access_finishing_sync.odbc import SourceRepository
from access_finishing_sync.payload import PreparedRequest, new_batch_id, prepare_request
from access_finishing_sync.response import IngestionOutcome
from access_finishing_sync.retry import RetryPolicy
from access_finishing_sync.submit import Submitter
from access_finishing_sync.transport import Transport
from access_finishing_sync.window import calculate_window

Action = Literal["check-config", "check-odbc", "dry-run", "run-once"]
RunStatus = Literal["success", "attention_required", "failed"]

MAX_LOGGED_ISSUES = 100
ATTENTION_REASONS = frozenset(
    {
        "empty_window",
        "window_too_large",
        "local_validation_failed",
        "unexpected_columns",
        "stale_batch",
        "batch_id_conflict",
    }
)


class SyncService:
    def __init__(
        self,
        config: Config,
        *,
        log: RunLogger,
        redactor: Redactor,
        credential_provider_factory: Callable[[], CredentialProvider],
        repository_factory: Callable[[], SourceRepository],
        transport_factory: Callable[[], Transport],
        lock_factory: Callable[[], AbstractContextManager[object]],
        today: Callable[[], dt.date] = dt.date.today,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._log = log
        self._redactor = redactor
        self._credential_provider_factory = credential_provider_factory
        self._repository_factory = repository_factory
        self._transport_factory = transport_factory
        self._lock_factory = lock_factory
        self._today = today
        self._now = now
        self._sleep = sleep
        self._jitter = jitter
        self._uuid_factory = uuid_factory
        self._monotonic = monotonic
        self._policy = RetryPolicy(max_attempts=config.http_max_attempts)

    # Entry point -----------------------------------------------------------------

    def execute(self, action: Action) -> ExitCode:
        handlers: dict[Action, Callable[[], tuple[ExitCode, RunStatus]]] = {
            "check-config": self.check_config,
            "check-odbc": self.check_odbc,
            "dry-run": self.dry_run,
            "run-once": self.run_once,
        }
        started = self._monotonic()
        self._log.info(
            "run_started",
            action=action,
            api_host=self._config.api_host,
            database_file=self._config.access_database_path.name,
            query=self._config.access_query_name,
        )
        try:
            code, status = handlers[action]()
        except ConnectorError as error:
            code = error.exit_code
            status = "attention_required" if error.reason in ATTENTION_REASONS else "failed"
            self._log.error("run_error", reason=error.reason, message=error.message, **error.fields)
        self._log.info(
            "run_finished",
            action=action,
            status=status,
            exit_code=int(code),
            elapsed_ms=round((self._monotonic() - started) * 1000),
        )
        return code

    @contextmanager
    def _phase(self, name: str) -> Iterator[None]:
        started = self._monotonic()
        try:
            yield
        finally:
            self._log.info(
                "phase_finished",
                phase=name,
                elapsed_ms=round((self._monotonic() - started) * 1000),
            )

    # Actions --------------------------------------------------------------------

    def check_config(self) -> tuple[ExitCode, RunStatus]:
        """Configuration was already validated on load; confirm the secret is
        retrievable. No Access query, no HTTP, no lock."""
        provider = self._credential_provider_factory()
        secret = provider.get_secret()
        self._redactor.add(secret.reveal())
        self._log.info(
            "configuration_valid",
            connector_id=self._config.connector_id,
            source_system=self._config.source_system,
            secret_source=provider.description,
            secret_available=True,
            reconciliation_days=self._config.reconciliation_days,
            batch_size=self._config.batch_size,
            development_mode=self._config.development_mode,
        )
        return ExitCode.SUCCESS, "success"

    def check_odbc(self) -> tuple[ExitCode, RunStatus]:
        """Driver, read-only connection, query selectable, columns present.
        Retrieves at most one row and never logs its values. No HTTP."""
        with self._phase("odbc_probe"):
            probe = self._repository_factory().probe()
        self._log.info(
            "odbc_probe",
            python_architecture=probe.python_architecture,
            readonly_attribute=probe.readonly_attribute,
            column_count=len(probe.columns),
            missing_columns=list(probe.missing_columns),
            test_row_retrieved=probe.row_retrieved,
        )
        if probe.missing_columns:
            raise OdbcUnavailableError(
                "The query is missing expected columns.",
                reason="missing_columns",
                missing_columns=list(probe.missing_columns),
            )
        return ExitCode.SUCCESS, "success"

    def dry_run(self) -> tuple[ExitCode, RunStatus]:
        """Full extraction and validation; nothing is sent or written to disk."""
        with self._lock_factory():
            request = self._prepare()
        self._log.info(
            "dry_run_complete",
            batch_id=request.batch_id,
            row_count=request.row_count,
            body_bytes=len(request.body),
            submitted=False,
        )
        return ExitCode.SUCCESS, "success"

    def run_once(self) -> tuple[ExitCode, RunStatus]:
        with self._lock_factory():
            secret = self._credential_provider_factory().get_secret()
            self._redactor.add(secret.reveal())
            request = self._prepare()
            transport = self._transport_factory()
            try:
                submitter = Submitter(
                    url=self._config.ingestion_url,
                    connector_id=self._config.connector_id,
                    source_system=self._config.source_system,
                    transport=transport,
                    policy=self._policy,
                    log=self._log,
                    sleep=self._sleep,
                    jitter=self._jitter,
                    now=self._now,
                )
                with self._phase("submit"):
                    outcome = submitter.submit(request, secret.reveal())
            finally:
                transport.close()
        return self._record(outcome)

    # Steps ----------------------------------------------------------------------

    def _prepare(self) -> PreparedRequest:
        config = self._config
        window = calculate_window(self._today(), config.reconciliation_days)
        self._log.info(
            "window_calculated",
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            days=window.days,
            query_upper_bound_exclusive=window.query_end_exclusive.date().isoformat(),
        )
        extracted_at = self._now()
        with self._phase("extract"):
            extraction = self._repository_factory().extract(window)
        count = len(extraction.rows)
        self._log.info(
            "extraction_finished",
            extracted_rows=count,
            readonly_attribute=extraction.readonly_attribute,
        )
        if count == 0:
            raise ExtractionError(
                "Access returned no rows for the reconciliation window. An empty window is "
                "never submitted because it would supersede every stored row in the range.",
                reason="empty_window",
                window_start=window.start.isoformat(),
                window_end=window.end.isoformat(),
            )

        with self._phase("map"):
            mapping = map_rows(extraction.rows, window)
        if mapping.rows_with_time_of_day:
            self._log.warning("date_time_of_day_dropped", row_count=mapping.rows_with_time_of_day)
        if mapping.issues:
            for issue in mapping.issues[:MAX_LOGGED_ISSUES]:
                self._log.warning(
                    "row_invalid", row_index=issue.row_index, field=issue.field, reason=issue.reason
                )
            invalid_rows = len({issue.row_index for issue in mapping.issues})
            raise ExtractionError(
                f"{invalid_rows} extracted rows failed local validation. The window is "
                "incomplete, so nothing was submitted.",
                reason="local_validation_failed",
                extracted_rows=count,
                invalid_rows=invalid_rows,
                issues=len(mapping.issues),
                issues_logged=min(len(mapping.issues), MAX_LOGGED_ISSUES),
            )

        if count > config.batch_size:
            raise ExtractionError(
                f"The reconciliation window contains {count} rows, above BATCH_SIZE="
                f"{config.batch_size} (API maximum {MAX_SERVER_BATCH_ROWS} rows per request). "
                "The API has no atomic multi-request reconciliation, so a partial window is "
                "never sent. Reduce RECONCILIATION_DAYS.",
                reason="window_too_large",
                extracted_rows=count,
                batch_size=config.batch_size,
                reconciliation_days=config.reconciliation_days,
            )

        batch_id = new_batch_id(
            config.source_system, config.connector_id, self._now(), self._uuid_factory
        )
        request = prepare_request(
            source_system=config.source_system,
            batch_id=batch_id,
            extracted_at=extracted_at,
            window=window,
            rows=mapping.rows,
        )
        self._log.info(
            "request_prepared",
            batch_id=batch_id,
            row_count=request.row_count,
            body_bytes=len(request.body),
            extracted_at=request.extracted_at,
        )
        return request

    def _record(self, outcome: IngestionOutcome) -> tuple[ExitCode, RunStatus]:
        self._log.info(
            "submission_result",
            batch_id=outcome.batch_id,
            status=outcome.status,
            replayed=outcome.replayed,
            received_rows=outcome.received_rows,
            inserted_rows=outcome.inserted_rows,
            duplicate_rows=outcome.duplicate_rows,
            rejected_rows=outcome.rejected_rows,
            superseded_rows=outcome.superseded_rows,
            restored_rows=outcome.restored_rows,
            window_applied=outcome.window_applied,
        )
        if outcome.rejected_rows == 0:
            return ExitCode.SUCCESS, "success"
        for rejection in outcome.rejections:
            self._log.warning(
                "row_rejected",
                batch_id=outcome.batch_id,
                row_index=rejection.row_index,
                errors=[{"field": field, "reason": reason} for field, reason in rejection.errors],
            )
        self._log.warning(
            "partial_acceptance",
            batch_id=outcome.batch_id,
            rejected_rows=outcome.rejected_rows,
            rejections_logged=len(outcome.rejections),
            rejections_truncated=outcome.rejections_truncated,
            window_applied=outcome.window_applied,
        )
        return ExitCode.PARTIAL_ACCEPTANCE, "attention_required"
