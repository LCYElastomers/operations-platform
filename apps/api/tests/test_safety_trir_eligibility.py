"""Unique-record TRIR eligibility and injury-outcome mutual exclusion."""

from decimal import Decimal
from typing import Any

import pytest

from app.safety.performance.calculations import (
    Measure,
    MonthHours,
    month_counts,
    rolling_window,
    shift,
    window_rate,
    ytd_window,
)
from app.safety.records.repository import Option
from app.safety.records.schemas import RecordDetailFields
from app.safety.records.service import RecordRuleError, _plan_details
from app.safety.trir_eligibility import (
    TRIR_CASES_KEY,
    has_multiple_injury_outcomes,
    is_trir_recordable,
)


def test_injury_outcomes_are_mutually_exclusive_flags() -> None:
    assert has_multiple_injury_outcomes({"recordable_injury", "lost_time_injury"})
    assert has_multiple_injury_outcomes({"recordable_injury", "restricted"})
    assert has_multiple_injury_outcomes({"lost_time_injury", "restricted"})
    assert has_multiple_injury_outcomes(
        {"recordable_injury", "lost_time_injury", "restricted"}
    )
    assert not has_multiple_injury_outcomes({"lost_time_injury"})
    assert not has_multiple_injury_outcomes({"recordable_injury", "fire"})


def test_trir_eligibility_covers_all_three_outcomes_and_illness() -> None:
    assert is_trir_recordable(["recordable_injury"])
    assert is_trir_recordable(["lost_time_injury"])
    assert is_trir_recordable(["restricted"])
    assert is_trir_recordable(["occupational_illness"])
    assert is_trir_recordable(["lost_time_injury", "recordable_injury"])
    assert not is_trir_recordable(["first_aid"])
    assert not is_trir_recordable(["fire"])


def test_recordable_only_classification_and_trir_case() -> None:
    counts = month_counts(
        "incidents",
        {"recordable_injury": 1, "lost_time_injury": 0, "restricted": 0, TRIR_CASES_KEY: 1},
        closed=True,
    )
    assert counts.recordable_injury == 1
    assert counts.trir == 1


def test_lost_time_row_zero_recordable_row_one_trir_case() -> None:
    counts = month_counts(
        "incidents",
        {"recordable_injury": 0, "lost_time_injury": 1, "restricted": 0, TRIR_CASES_KEY: 1},
        closed=True,
    )
    assert counts.recordable_injury == 0
    assert counts.trir == 1


def test_restricted_row_zero_recordable_row_one_trir_case() -> None:
    counts = month_counts(
        "incidents",
        {"recordable_injury": 0, "lost_time_injury": 0, "restricted": 1, TRIR_CASES_KEY: 1},
        closed=True,
    )
    assert counts.recordable_injury == 0
    assert counts.trir == 1


def test_month_counts_prefer_distinct_trir_cases_over_cell_sums() -> None:
    # Overlapping cell totals would imply 3; distinct records say 1.
    counts = month_counts(
        "incidents",
        {
            "recordable_injury": 1,
            "occupational_illness": 1,
            TRIR_CASES_KEY: 1,
        },
        closed=True,
    )
    assert counts.trir == 1
    assert counts.recordable_injury == 1
    assert counts.occupational_illness == 1


def test_month_counts_fall_back_to_ri_plus_oi_without_trir_cases() -> None:
    counts = month_counts(
        "incidents",
        {"recordable_injury": 2, "occupational_illness": 1},
        closed=True,
    )
    assert counts.trir == 3


def test_august_lti_regression_numerator_is_one_not_two() -> None:
    """One August LTI: classification LTI=1, RI cells may be wrong historically; TRIR=1."""
    counts = month_counts(
        "incidents",
        {
            "recordable_injury": 1,  # mistaken double-count cell
            "lost_time_injury": 1,  # display-only; not read into trir_cases path
            TRIR_CASES_KEY: 1,
        },
        closed=True,
    )
    assert counts.trir == 1
    assert counts.recordable_injury == 1  # cell still readable for the grid


def test_historical_lti_plus_recordable_contributes_one() -> None:
    assert is_trir_recordable(["lost_time_injury", "recordable_injury"])
    counts = month_counts(
        "incidents",
        {"recordable_injury": 1, "lost_time_injury": 1, TRIR_CASES_KEY: 1},
        closed=True,
    )
    assert counts.trir == 1


def test_historical_restricted_plus_recordable_contributes_one() -> None:
    counts = month_counts(
        "incidents",
        {"recordable_injury": 1, "restricted": 1, TRIR_CASES_KEY: 1},
        closed=True,
    )
    assert counts.trir == 1


def test_historical_all_three_outcomes_contribute_one() -> None:
    counts = month_counts(
        "incidents",
        {
            "recordable_injury": 1,
            "lost_time_injury": 1,
            "restricted": 1,
            TRIR_CASES_KEY: 1,
        },
        closed=True,
    )
    assert counts.trir == 1


def test_voided_qualifying_event_is_zero_cases() -> None:
    # Voided/superseded rows never appear in trir_case_counts; empty overlay → 0.
    counts = month_counts(
        "incidents",
        {"recordable_injury": 0, "lost_time_injury": 0, TRIR_CASES_KEY: 0},
        closed=True,
    )
    assert counts.trir == 0


def test_ytd_and_rolling_use_trir_cases_not_cell_sums() -> None:
    end = (2026, 8)
    hours = {
        period: MonthHours(total_hours=Decimal("10000"), month_closed=True)
        for period in [*rolling_window(end)]
    }

    def stored(period: tuple[int, int]) -> dict[str, int]:
        if period == end:
            return {
                "recordable_injury": 1,
                "lost_time_injury": 1,
                TRIR_CASES_KEY: 1,
            }
        return {TRIR_CASES_KEY: 0}

    counts = {
        period: month_counts("incidents", stored(period), closed=True) for period in hours
    }
    ytd = window_rate(Measure.TRIR, ytd_window(end), hours, counts)
    rolling = window_rate(Measure.TRIR, rolling_window(end), hours, counts)
    assert ytd.available and ytd.events == 1
    assert rolling.available and rolling.events == 1
    assert shift(end, -11) in hours


def test_hours_denominator_unchanged_with_trir_cases() -> None:
    hours = {(2026, 1): MonthHours(total_hours=Decimal("20000"), month_closed=True)}
    without = {
        (2026, 1): month_counts(
            "incidents", {"recordable_injury": 1, "occupational_illness": 0}, closed=True
        )
    }
    with_cases = {
        (2026, 1): month_counts(
            "incidents",
            {"recordable_injury": 1, "occupational_illness": 0, TRIR_CASES_KEY: 1},
            closed=True,
        )
    }
    a = window_rate(Measure.TRIR, ytd_window((2026, 1)), hours, without)
    b = window_rate(Measure.TRIR, ytd_window((2026, 1)), hours, with_cases)
    assert a.hours == b.hours == Decimal("20000")
    assert a.events == b.events == 1


class _FakeRecordRepo:
    def classifications(self) -> list[Option]:
        return [
            Option(10, "recordable_injury", "Recordable Injury", True),
            Option(11, "lost_time_injury", "Lost Time Injury", True),
            Option(12, "restricted", "Restricted", True),
            Option(2, "fire", "Fire", True),
        ]

    def further_classification_ids(self, record_id: int | None) -> list[int]:
        return []

    def tag_ids(self, tag: Any, record_id: int | None) -> list[int]:
        return []

    def tag_options(self, tag: Any) -> list[Option]:
        return []

    def detail(self, spec: Any, record_id: int | None) -> None:
        return None

    def detail_codes(self) -> dict[str, list[tuple[str, str, bool]]]:
        return {}


@pytest.mark.parametrize(
    "primary, additional",
    [
        (10, [11]),
        (10, [12]),
        (11, [12]),
        (11, [10, 12]),
    ],
)
def test_backend_rejects_multiple_injury_outcomes(primary: int, additional: list[int]) -> None:
    request = RecordDetailFields.model_validate({"additionalClassificationIds": additional})
    with pytest.raises(RecordRuleError) as raised:
        _plan_details(
            _FakeRecordRepo(),  # type: ignore[arg-type]
            request,
            record_id=None,
            primary_id=primary,
            strict=True,
        )
    assert raised.value.error == "injury_outcome_conflict"


def test_backend_allows_single_injury_outcome_with_other_classifications() -> None:
    request = RecordDetailFields.model_validate({"additionalClassificationIds": [2]})
    plan = _plan_details(
        _FakeRecordRepo(),  # type: ignore[arg-type]
        request,
        record_id=None,
        primary_id=11,
        strict=True,
    )
    assert plan.further_after == [2]


def test_reviewed_import_may_keep_overlapping_outcomes_when_not_strict() -> None:
    request = RecordDetailFields.model_validate({"additionalClassificationIds": [11]})
    plan = _plan_details(
        _FakeRecordRepo(),  # type: ignore[arg-type]
        request,
        record_id=None,
        primary_id=10,
        strict=False,
    )
    assert set(plan.further_after) == {11}
