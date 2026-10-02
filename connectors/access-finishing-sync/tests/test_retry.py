import datetime as dt

import pytest

from access_finishing_sync.retry import TRANSIENT_STATUSES, RetryPolicy, parse_retry_after

NOW = dt.datetime(2026, 10, 2, 17, 40, tzinfo=dt.UTC)


def test_transient_statuses() -> None:
    assert frozenset({429, 502, 503, 504}) == TRANSIENT_STATUSES


def test_backoff_grows_exponentially_with_jitter() -> None:
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=60)

    assert [policy.backoff(n, 0.0) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]
    assert [policy.backoff(n, 0.999999) for n in (1, 2, 3)] == pytest.approx([2, 4, 8], abs=1e-4)


@pytest.mark.parametrize("retry_number", range(1, 30))
@pytest.mark.parametrize("jitter", [0.0, 0.5, 0.999])
def test_backoff_is_bounded(retry_number: int, jitter: float) -> None:
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=60)

    assert 0 < policy.backoff(retry_number, jitter) <= 60


def test_retry_after_seconds() -> None:
    assert parse_retry_after("7", NOW) == 7


def test_retry_after_http_date() -> None:
    assert parse_retry_after("Fri, 02 Oct 2026 17:40:30 GMT", NOW) == 30


def test_retry_after_in_the_past_means_now() -> None:
    assert parse_retry_after("Fri, 02 Oct 2026 17:00:00 GMT", NOW) == 0


@pytest.mark.parametrize("value", [None, "", "soon", "-5", "1.5", "99999999999"])
def test_unsupported_retry_after_is_ignored(value: str | None) -> None:
    assert parse_retry_after(value, NOW) is None


def test_retry_after_is_preferred_but_capped() -> None:
    policy = RetryPolicy(max_retry_after_seconds=120)

    assert policy.delay(1, 0.5, "7", NOW) == 7
    assert policy.delay(1, 0.5, "86400", NOW) == 120
    assert policy.delay(1, 0.0, None, NOW) == policy.backoff(1, 0.0)
