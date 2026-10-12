"""Reporting periods shared by every dashboard, register and export.

The web's ``src/lib/period.ts`` resolves the same modes with the same rules, so
a screen and its export cover the same dates. Dates are Baytown site calendar
dates (``app.safety.site_calendar``); a period's ``end`` is inclusive.
"""

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.schemas import CamelModel

PeriodMode = Literal[
    "all",
    "this-month",
    "last-month",
    "ytd",
    "last-3-months",
    "last-6-months",
    "this-year",
    "year",
    "month",
    "custom",
]

MIN_YEAR = 2000
MAX_YEAR = 2100

MODE_LABELS: dict[str, str] = {
    "all": "All dates",
    "this-month": "This Month",
    "last-month": "Last Month",
    "ytd": "Year to Date",
    "last-3-months": "Last 3 Months",
    "last-6-months": "Last 6 Months",
    "this-year": "This Year",
}


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    """A resolved period. ``start`` / ``end`` are None only for "all"."""

    mode: str
    start: dt.date | None
    end: dt.date | None
    year: int | None
    month: int | None
    label: str
    """Short name: "Year to Date", "August 2026", "2026", "Custom Range"."""
    range_label: str
    """The dates covered: "Jan 1 – Oct 9, 2026"; "" for all dates."""

    @property
    def full_label(self) -> str:
        if not self.range_label or self.range_label == self.label:
            return self.label
        return f"{self.label} · {self.range_label}"

    @property
    def filename_part(self) -> str:
        """``2026-08``, ``2026-YTD``, ``2026``, ``2026-01-01_2026-03-31`` or ``All-Dates``."""
        if self.start is None or self.end is None:
            return "All-Dates"
        if self.mode == "ytd":
            return f"{self.end.year}-YTD"
        if self.mode in ("this-year", "year"):
            return str(self.start.year)
        if self.mode in ("this-month", "last-month", "month"):
            return f"{self.start.year}-{self.start.month:02d}"
        return f"{self.start.isoformat()}_{self.end.isoformat()}"


def last_day(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _short(day: dt.date) -> str:
    return f"{calendar.month_abbr[day.month]} {day.day}"


def range_label(start: dt.date, end: dt.date) -> str:
    """``Jan 1 – Oct 9, 2026``; ``Nov 1, 2025 – Jan 31, 2026`` across years."""
    if start == end:
        return f"{_short(start)}, {start.year}"
    if start.year == end.year:
        return f"{_short(start)} – {_short(end)}, {end.year}"
    return f"{_short(start)}, {start.year} – {_short(end)}, {end.year}"


def _month_name(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def resolve(
    mode: str,
    today: dt.date,
    *,
    year: int | None = None,
    month: int | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> Period:
    """The dates of ``mode`` on the site date ``today``."""
    if mode == "all":
        return Period("all", None, None, None, None, MODE_LABELS["all"], "")
    if mode == "this-month":
        first = today.replace(day=1)
        return _period(mode, first, last_day(today.year, today.month), MODE_LABELS[mode])
    if mode == "last-month":
        y, m = add_months(today.year, today.month, -1)
        return _period(mode, dt.date(y, m, 1), last_day(y, m), MODE_LABELS[mode])
    if mode == "ytd":
        return _period(mode, dt.date(today.year, 1, 1), today, MODE_LABELS[mode])
    if mode in ("last-3-months", "last-6-months"):
        count = 3 if mode == "last-3-months" else 6
        y, m = add_months(today.year, today.month, -(count - 1))
        return _period(mode, dt.date(y, m, 1), last_day(today.year, today.month), MODE_LABELS[mode])
    if mode == "this-year":
        return _period(
            mode, dt.date(today.year, 1, 1), dt.date(today.year, 12, 31), MODE_LABELS[mode]
        )
    if mode == "year":
        if year is None:
            raise PeriodError("A year is required.")
        _check_year(year)
        return _period(mode, dt.date(year, 1, 1), dt.date(year, 12, 31), str(year))
    if mode == "month":
        if year is None or month is None:
            raise PeriodError("A year and month are required.")
        _check_year(year)
        if not 1 <= month <= 12:
            raise PeriodError("Month must be 1 to 12.")
        return _period(
            mode, dt.date(year, month, 1), last_day(year, month), _month_name(year, month)
        )
    if mode == "custom":
        if start is None or end is None:
            raise PeriodError("A custom range needs a from and a to date.")
        if end < start:
            raise PeriodError("The to date is before the from date.")
        _check_year(start.year)
        _check_year(end.year)
        return _period(mode, start, end, "Custom Range")
    raise PeriodError(f"Unknown period {mode!r}.")


def _check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise PeriodError(f"Year must be {MIN_YEAR} to {MAX_YEAR}.")


def _period(mode: str, start: dt.date, end: dt.date, label: str) -> Period:
    single_month = mode in ("this-month", "last-month", "month")
    single_year = start == dt.date(start.year, 1, 1) and end == dt.date(start.year, 12, 31)
    year = start.year if start.year == end.year else None
    month = start.month if single_month else None
    if mode == "month":
        text = range_label(start, end)
    elif mode in ("this-month", "last-month"):
        text = _month_name(start.year, start.month)
    elif single_year and mode in ("this-year", "year"):
        text = str(start.year)
    else:
        text = range_label(start, end)
    return Period(mode, start, end, year, month, label, text)


class PeriodIn(CamelModel):
    """A period as the web sends it; resolved on the server with the site date."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: PeriodMode = "all"
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    month: int | None = Field(default=None, ge=1, le=12)
    from_: dt.date | None = Field(default=None, alias="from")
    to: dt.date | None = None

    @model_validator(mode="after")
    def _complete(self) -> "PeriodIn":
        try:
            self.resolve(dt.date(2000, 1, 1))
        except PeriodError as error:
            raise ValueError(str(error)) from None
        return self

    def resolve(self, today: dt.date) -> Period:
        return resolve(
            self.mode, today, year=self.year, month=self.month, start=self.from_, end=self.to
        )
