import datetime as dt

import pytest

from access_finishing_sync.window import DateWindow, calculate_window


def test_window_covers_the_configured_number_of_days_ending_today() -> None:
    window = calculate_window(dt.date(2026, 10, 2), 60)

    assert window == DateWindow(start=dt.date(2026, 8, 4), end=dt.date(2026, 10, 2))
    assert window.days == 60


def test_single_day_window() -> None:
    window = calculate_window(dt.date(2026, 10, 2), 1)

    assert window.start == window.end == dt.date(2026, 10, 2)


def test_boundaries_are_inclusive() -> None:
    window = calculate_window(dt.date(2026, 10, 2), 3)

    assert window.contains(dt.date(2026, 9, 30))
    assert window.contains(dt.date(2026, 10, 2))
    assert not window.contains(dt.date(2026, 9, 29))
    assert not window.contains(dt.date(2026, 10, 3))


def test_query_upper_boundary_is_the_exclusive_next_midnight() -> None:
    window = calculate_window(dt.date(2026, 10, 2), 3)

    assert window.query_start == dt.datetime(2026, 9, 30, 0, 0)
    assert window.query_end_exclusive == dt.datetime(2026, 10, 3, 0, 0)


@pytest.mark.parametrize(
    ("today", "days", "start", "exclusive_end"),
    [
        (dt.date(2024, 3, 1), 2, dt.date(2024, 2, 29), dt.datetime(2024, 3, 2)),
        (dt.date(2027, 1, 1), 5, dt.date(2026, 12, 28), dt.datetime(2027, 1, 2)),
        (dt.date(2026, 12, 31), 1, dt.date(2026, 12, 31), dt.datetime(2027, 1, 1)),
    ],
)
def test_calendar_boundaries(
    today: dt.date, days: int, start: dt.date, exclusive_end: dt.datetime
) -> None:
    window = calculate_window(today, days)

    assert window.start == start
    assert window.query_end_exclusive == exclusive_end


def test_zero_days_is_invalid() -> None:
    with pytest.raises(ValueError):
        calculate_window(dt.date(2026, 10, 2), 0)
