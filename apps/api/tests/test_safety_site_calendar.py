"""The Baytown site calendar decides today's date and the current reporting year."""

import datetime as dt

import pytest

from app.safety.site_calendar import site_today

CST = dt.timezone(dt.timedelta(hours=-6))


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (dt.datetime(2026, 12, 31, 23, 59, 59, tzinfo=CST), dt.date(2026, 12, 31)),
        (dt.datetime(2027, 1, 1, 0, 0, 0, tzinfo=CST), dt.date(2027, 1, 1)),
        (dt.datetime(2027, 1, 1, 5, 59, 59, tzinfo=dt.UTC), dt.date(2026, 12, 31)),
        (dt.datetime(2027, 1, 1, 6, 0, 0, tzinfo=dt.UTC), dt.date(2027, 1, 1)),
        # UTC midnight is 18:00 on 31 December in Baytown.
        (dt.datetime(2027, 1, 1, 0, 0, 0, tzinfo=dt.UTC), dt.date(2026, 12, 31)),
        # Tokyo (+09:00) is already in 2027 at 15:00 on 31 December in Baytown.
        (
            dt.datetime(2027, 1, 1, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=9))),
            dt.date(2026, 12, 31),
        ),
        # Los Angeles (-08:00) is still in 2026 at midnight in Baytown.
        (
            dt.datetime(2026, 12, 31, 22, 0, tzinfo=dt.timezone(dt.timedelta(hours=-8))),
            dt.date(2027, 1, 1),
        ),
        (dt.datetime(2026, 10, 8, 4, 59, tzinfo=dt.UTC), dt.date(2026, 10, 7)),  # 23:59 CDT
        (dt.datetime(2026, 10, 8, 5, 0, tzinfo=dt.UTC), dt.date(2026, 10, 8)),  # midnight CDT
        (dt.datetime(2026, 3, 9, 4, 59, tzinfo=dt.UTC), dt.date(2026, 3, 8)),  # DST began 8 March
        (dt.datetime(2026, 3, 9, 5, 0, tzinfo=dt.UTC), dt.date(2026, 3, 9)),
        (
            dt.datetime(2026, 10, 7, 23, 0, tzinfo=dt.timezone(dt.timedelta(hours=5))),
            dt.date(2026, 10, 7),
        ),
    ],
)
def test_site_today_is_the_baytown_calendar_date(instant: dt.datetime, expected: dt.date) -> None:
    assert site_today(instant) == expected
    assert site_today(instant).year == expected.year
