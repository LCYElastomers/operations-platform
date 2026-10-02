"""Authoritative reconciliation window (strategy B)."""

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class DateWindow:
    """Inclusive source-date range declared to the API as reconciliationWindow."""

    start: dt.date
    end: dt.date

    @property
    def query_start(self) -> dt.datetime:
        """Inclusive lower bound for the Access query."""
        return dt.datetime.combine(self.start, dt.time.min)

    @property
    def query_end_exclusive(self) -> dt.datetime:
        """Exclusive upper bound: midnight after the window end, so DATE values
        carrying a time of day on the last day are still included."""
        return dt.datetime.combine(self.end + dt.timedelta(days=1), dt.time.min)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: dt.date) -> bool:
        return self.start <= day <= self.end


def calculate_window(today: dt.date, reconciliation_days: int) -> DateWindow:
    """The last `reconciliation_days` calendar days, ending today (local time)."""
    if reconciliation_days < 1:
        raise ValueError("reconciliation_days must be at least 1")
    return DateWindow(start=today - dt.timedelta(days=reconciliation_days - 1), end=today)
