"""Authenticated submission of one prepared request, with bounded retries.

Every attempt sends the identical `PreparedRequest.body` (same batchId, same
extractedAt, same bytes). Nothing is rebuilt between attempts.
"""

import datetime as dt
import random
import time
from collections.abc import Callable

from access_finishing_sync.errors import TransientFailureError
from access_finishing_sync.logs import RunLogger
from access_finishing_sync.payload import PreparedRequest
from access_finishing_sync.response import (
    IngestionOutcome,
    classify_failure,
    parse_ingestion_result,
)
from access_finishing_sync.retry import TRANSIENT_STATUSES, RetryPolicy
from access_finishing_sync.transport import Transport, TransportError

CONNECTOR_ID_HEADER = "X-Connector-Id"


class Submitter:
    def __init__(
        self,
        *,
        url: str,
        connector_id: str,
        source_system: str,
        transport: Transport,
        policy: RetryPolicy,
        log: RunLogger,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._url = url
        self._connector_id = connector_id
        self._source_system = source_system
        self._transport = transport
        self._policy = policy
        self._log = log
        self._sleep = sleep
        self._jitter = jitter
        self._now = now

    def submit(self, request: PreparedRequest, secret_value: str) -> IngestionOutcome:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            CONNECTOR_ID_HEADER: self._connector_id,
            "Authorization": f"Bearer {secret_value}",
        }
        attempts = self._policy.max_attempts
        for attempt in range(1, attempts + 1):
            retry_after: str | None = None
            try:
                response = self._transport.post(self._url, request.body, headers)
            except TransportError as error:
                self._log.warning(
                    "http_attempt_failed",
                    batch_id=request.batch_id,
                    attempt=attempt,
                    failure=error.kind,
                    error_type=error.error_type,
                )
                outcome = f"network_{error.kind}"
            else:
                if response.status == 200:
                    self._log.info(
                        "http_attempt", batch_id=request.batch_id, attempt=attempt, http_status=200
                    )
                    return parse_ingestion_result(response.body, request, self._source_system)
                if response.status not in TRANSIENT_STATUSES:
                    failure = classify_failure(response.status, response.body)
                    self._log.warning(
                        "http_attempt",
                        batch_id=request.batch_id,
                        attempt=attempt,
                        http_status=response.status,
                        error_code=failure.reason,
                    )
                    raise failure
                retry_after = response.headers.get("retry-after")
                self._log.warning(
                    "http_attempt",
                    batch_id=request.batch_id,
                    attempt=attempt,
                    http_status=response.status,
                    retryable=True,
                )
                outcome = f"http_{response.status}"

            if attempt == attempts:
                raise TransientFailureError(
                    f"The API could not be reached successfully after {attempts} attempts.",
                    reason="retries_exhausted",
                    attempts=attempts,
                    last_outcome=outcome,
                )
            delay = self._policy.delay(attempt, self._jitter(), retry_after, self._now())
            self._log.info(
                "http_retry_scheduled",
                batch_id=request.batch_id,
                next_attempt=attempt + 1,
                delay_seconds=round(delay, 3),
            )
            self._sleep(delay)
        raise AssertionError("unreachable")
