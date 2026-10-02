import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from support import source_row

from access_finishing_sync.mapping import (
    FieldValueError,
    map_identifier,
    map_measurement,
    map_rows,
)
from access_finishing_sync.window import calculate_window

WINDOW = calculate_window(dt.date(2026, 10, 2), 60)


def mapped(**overrides: Any) -> dict[str, Any]:
    result = map_rows([source_row(**overrides)], WINDOW)
    assert result.issues == []
    return result.rows[0]


def issues(**overrides: Any) -> list[tuple[str, str]]:
    result = map_rows([source_row(**overrides)], WINDOW)
    assert result.rows == []
    return [(issue.field, issue.reason) for issue in result.issues]


def test_source_fields_map_to_api_fields_in_order() -> None:
    row = mapped()

    assert list(row) == [
        "sourceDate",
        "campaignNo",
        "lot",
        "location",
        "product",
        "avgMoisture",
        "avgColor",
        "avgCombinedBd",
    ]
    assert row == {
        "sourceDate": "2026-10-01",
        "campaignNo": "26101",
        "lot": "A260901-01",
        "location": "Silo 1",
        "product": "PRD-A",
        "avgMoisture": Decimal("0.4"),
        "avgColor": Decimal("40"),
        "avgCombinedBd": Decimal("0.7"),
    }


def test_date_values_become_iso_calendar_dates() -> None:
    assert mapped(day=dt.date(2026, 9, 1))["sourceDate"] == "2026-09-01"


def test_datetime_values_become_iso_calendar_dates() -> None:
    assert mapped(day=dt.datetime(2026, 9, 1, 0, 0))["sourceDate"] == "2026-09-01"


def test_time_of_day_is_dropped_and_counted() -> None:
    result = map_rows([source_row(day=dt.datetime(2026, 9, 1, 13, 45))], WINDOW)

    assert result.rows[0]["sourceDate"] == "2026-09-01"
    assert result.rows_with_time_of_day == 1


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("2026-09-01", "has unsupported type str"),
        ("09/01/2026", "has unsupported type str"),
        (20260901, "has unsupported type int"),
        (None, "is missing"),
        (dt.datetime(2026, 9, 1, tzinfo=dt.UTC), "has an unsupported time zone"),
        (dt.date(2026, 10, 3), "is outside the reconciliation window"),
        (dt.date(2026, 8, 3), "is outside the reconciliation window"),
    ],
)
def test_malformed_or_unsupported_dates_are_rejected(value: Any, reason: str) -> None:
    assert issues(day=value) == [("DATE", reason)]


def test_null_measurements_stay_null() -> None:
    row = mapped(moisture=None, color=None, bulk_density=None)

    assert (row["avgMoisture"], row["avgColor"], row["avgCombinedBd"]) == (None, None, None)


@pytest.mark.parametrize("zero", [0, 0.0, Decimal("0"), Decimal("0.000")])
def test_numeric_zero_stays_zero(zero: Any) -> None:
    value = mapped(moisture=zero)["avgMoisture"]

    assert value is not None
    assert value == 0
    assert isinstance(value, Decimal)


def test_decimal_values_are_preserved_exactly() -> None:
    value = Decimal("0.1234567890123456789012345")

    assert mapped(moisture=value)["avgMoisture"] is value
    assert str(mapped(color=Decimal("40.10"))["avgColor"]) == "40.10"


@pytest.mark.parametrize(
    ("value", "text"),
    [(0.1, "0.1"), (0.43333333333333335, "0.43333333333333335"), (1e-7, "1E-7"), (-2.5, "-2.5")],
)
def test_floats_are_converted_through_their_text_form(value: float, text: str) -> None:
    result = map_measurement(value)

    assert result == Decimal(str(value))
    assert str(result) == text
    assert result != Decimal(value) or text == "-2.5"  # Decimal(float) would expose binary noise


def test_integers_become_exact_decimals() -> None:
    assert map_measurement(7) == Decimal(7)


@pytest.mark.parametrize("value", [float("nan"), Decimal("NaN"), Decimal("sNaN")])
def test_nan_is_rejected(value: Any) -> None:
    assert issues(moisture=value) == [("AvgOfMOISTURE", "is NaN")]


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), Decimal("Infinity")])
def test_infinity_is_rejected(value: Any) -> None:
    assert issues(color=value) == [("AvgOfCOLOR", "is infinite")]


@pytest.mark.parametrize("value", ["0.4", True, b"0.4"])
def test_non_numeric_measurements_are_rejected(value: Any) -> None:
    assert issues(bulk_density=value)[0][0] == "AvgOfCombined_BD"


def test_unusual_values_are_not_rejected() -> None:
    row = mapped(moisture=Decimal("-12.5"), color=Decimal("999999"))

    assert (row["avgMoisture"], row["avgColor"]) == (Decimal("-12.5"), Decimal("999999"))


@pytest.mark.parametrize("location", ["  SILO 1 ", "silo 1", "Silo-1.", "", "Rail/Car #2"])
def test_raw_location_is_preserved(location: str) -> None:
    assert mapped(location=location)["location"] == location


def test_missing_location_is_not_substituted() -> None:
    assert mapped(location=None)["location"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("campno", "00261"), ("lot", "007-A"), ("product", "0042"), ("campno", "26101.0")],
)
def test_string_identifiers_are_preserved_with_leading_zeroes(field: str, value: str) -> None:
    api_field = {"campno": "campaignNo", "lot": "lot", "product": "product"}[field]

    assert mapped(**{field: value})[api_field] == value


def test_missing_identifiers_are_not_invented() -> None:
    row = mapped(campno=None, lot=None, product=None)

    assert (row["campaignNo"], row["lot"], row["product"]) == (None, None, None)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (26101, "26101"),
        (26101.0, "26101"),
        (Decimal("26101"), "26101"),
        (Decimal("2.6101E+4"), "26101"),
    ],
)
def test_numeric_identifiers_become_their_integer_text(value: Any, text: str) -> None:
    assert map_identifier(value) == text


@pytest.mark.parametrize("value", [26101.5, Decimal("1.5"), True, b"x", float("nan")])
def test_non_integral_or_unsupported_identifiers_are_rejected(value: Any) -> None:
    with pytest.raises(FieldValueError):
        map_identifier(value)


def test_overlong_identifier_is_rejected() -> None:
    assert issues(lot="L" * 201) == [("LOT", "is longer than 200 characters")]


def test_all_issues_of_a_row_are_reported_without_values() -> None:
    result = map_rows(
        [source_row(), source_row(day="bad-date", moisture=float("nan"), lot="SECRET-LOT" * 30)],
        WINDOW,
    )

    assert len(result.rows) == 1
    assert [(i.row_index, i.field) for i in result.issues] == [
        (1, "DATE"),
        (1, "LOT"),
        (1, "AvgOfMOISTURE"),
    ]
    assert all("SECRET-LOT" not in i.reason and "bad-date" not in i.reason for i in result.issues)


def test_wrong_column_count_is_rejected() -> None:
    result = map_rows([("2026-09-01",)], WINDOW)

    assert result.issues[0].field == "*"
