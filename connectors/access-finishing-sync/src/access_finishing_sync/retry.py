"""Bounded exponential backoff with jitter, honouring Retry-After."""

import datetime as dt
import email.utils
from dataclasses import dataclass

TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    max_retry_after_seconds: float = 120.0

    def backoff(self, retry_number: int, jitter: float) -> float:
        """Delay before retry `retry_number` (1-based). `jitter` is in [0, 1)."""
        ceiling = min(self.max_delay_seconds, self.base_delay_seconds * 2 ** (retry_number - 1))
        return ceiling / 2 + ceiling / 2 * jitter

    def delay(
        self, retry_number: int, jitter: float, retry_after: str | None, now: dt.datetime
    ) -> float:
        requested = parse_retry_after(retry_after, now)
        if requested is not None:
            return min(requested, self.max_retry_after_seconds)
        return self.backoff(retry_number, jitter)


def parse_retry_after(value: str | None, now: dt.datetime) -> float | None:
    """Delta-seconds or an HTTP-date; None if absent or unsupported."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit() and len(value) <= 9:
        return float(value)
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if moment is None or moment.tzinfo is None:
        return None
    return max(0.0, (moment - now).total_seconds())
