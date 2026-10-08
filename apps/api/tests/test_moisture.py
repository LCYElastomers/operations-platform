import datetime as dt
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.quality.moisture.repository import FixtureMoistureRepository, get_moisture_repository
from app.quality.moisture.schemas import MoistureRecord
from app.quality.moisture.source import load_fixture_records, record_from_source_row

BASE = "/api/v1/quality/moisture"


def source_row(**overrides: Any) -> dict[str, Any]:
    """A test row using the Access source field names."""
    row: dict[str, Any] = {
        "DATE": "2026-09-01",
        "CAMPNO": "26101",
        "LOT": "A260901-01",
        "Location": "Silo 1",
        "PRODUCT": "PRD-A",
        "AvgOfMOISTURE": 0.4,
        "AvgOfCOLOR": 40.0,
        "AvgOfCombined_BD": 0.7,
    }
    row.update(overrides)
    return row


def records(*rows: dict[str, Any]) -> tuple[MoistureRecord, ...]:
    return tuple(record_from_source_row(row) for row in rows)


@pytest.fixture
def use_records() -> Iterator[Any]:
    """Returns a function that builds a client serving the given records."""
    clients: list[TestClient] = []

    def build(data: Sequence[MoistureRecord]) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_moisture_repository] = lambda: FixtureMoistureRepository(
            tuple(data)
        )
        client = TestClient(app)
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.close()


SAMPLE = records(
    source_row(DATE="2026-09-01", LOT="A260901-01", CAMPNO="26101", PRODUCT="PRD-A",
               Location="Silo 1", AvgOfMOISTURE=0.0),
    source_row(DATE="2026-09-02", LOT="B260902-02", CAMPNO="26201", PRODUCT="PRD-B",
               Location="SILO 1", AvgOfMOISTURE=None),
    source_row(DATE="2026-09-03", LOT="A260903-03", CAMPNO="26102", PRODUCT="PRD-A",
               Location="Railcar", AvgOfMOISTURE=0.5),
    source_row(DATE="2026-09-04", LOT=None, CAMPNO="26202", PRODUCT="PRD-B",
               Location="Silo 2", AvgOfMOISTURE=0.6),
)  # fmt: skip


def lots(response_json: dict[str, Any]) -> list[str | None]:
    return [record["lot"] for record in response_json["records"]]


def lot_ids(response_json: dict[str, Any]) -> list[str | None]:
    return [lot["lot"] for lot in response_json["lots"]]


# Source mapping ----------------------------------------------------------------


def test_source_fields_map_to_domain_names() -> None:
    record = record_from_source_row(source_row(AvgOfMOISTURE=0.43333333333333335))

    assert record.date == dt.date(2026, 9, 1)
    assert record.campaign_no == "26101"
    assert record.lot == "A260901-01"
    assert record.location == "Silo 1"
    assert record.product == "PRD-A"
    assert record.avg_moisture == 0.43333333333333335
    assert record.avg_color == 40.0
    assert record.avg_combined_bd == 0.7


def test_numeric_identifiers_are_kept_as_text() -> None:
    record = record_from_source_row(source_row(CAMPNO=26101, LOT=1234, PRODUCT=7))

    assert record.campaign_no == "26101"
    assert record.lot == "1234"
    assert record.product == "7"


def test_missing_source_field_is_rejected() -> None:
    row = source_row()
    del row["AvgOfCOLOR"]

    with pytest.raises(ValueError, match="AvgOfCOLOR"):
        record_from_source_row(row)


def test_development_fixture_loads_and_is_labeled(use_records: Any) -> None:
    assert len(load_fixture_records()) > 50
    client = TestClient(create_app())

    for path in ("/recent", "/lots", "/trends", "/filters"):
        body = client.get(BASE + path).json()
        assert body["dataSource"] == {
            "kind": "development-fixture",
            "isFixture": True,
            "label": "Development fixture. Not production data.",
        }


# Null versus zero ------------------------------------------------------------


def test_zero_and_null_are_serialized_distinctly(use_records: Any) -> None:
    client = use_records(SAMPLE)

    body = client.get(BASE + "/recent").json()
    by_lot = {record["lot"]: record for record in body["records"]}

    assert by_lot["A260901-01"]["avgMoisture"] == 0
    assert by_lot["A260901-01"]["avgMoisture"] is not None
    assert by_lot["B260902-02"]["avgMoisture"] is None


def test_source_precision_is_preserved(use_records: Any) -> None:
    client = use_records(records(source_row(AvgOfMOISTURE=0.43333333333333335)))

    record = client.get(BASE + "/recent").json()["records"][0]

    assert record["avgMoisture"] == 0.43333333333333335


def test_summary_counts_zero_and_skips_null(use_records: Any) -> None:
    client = use_records(SAMPLE)

    summary = client.get(BASE + "/trends").json()["summary"]

    # Values 0.0, 0.5, 0.6 (null excluded, zero included).
    assert summary["lotCount"] == 4
    assert summary["recordCount"] == 4
    assert summary["moistureValueCount"] == 3
    assert summary["avgMoisture"] == pytest.approx(1.1 / 3)


def test_summary_mean_is_null_when_all_values_are_null(use_records: Any) -> None:
    client = use_records(records(source_row(AvgOfCOLOR=None), source_row(AvgOfCOLOR=None)))

    summary = client.get(BASE + "/trends").json()["summary"]

    assert summary["avgColor"] is None
    assert summary["colorValueCount"] == 0


def test_summary_mean_of_zeros_is_zero(use_records: Any) -> None:
    client = use_records(records(source_row(AvgOfCOLOR=0.0), source_row(AvgOfCOLOR=0.0)))

    summary = client.get(BASE + "/trends").json()["summary"]

    assert summary["avgColor"] == 0
    assert summary["colorValueCount"] == 2


# Latest 50 -------------------------------------------------------------------


def _many(count: int) -> tuple[MoistureRecord, ...]:
    start = dt.date(2026, 1, 1)
    return records(
        *(
            source_row(DATE=(start + dt.timedelta(days=i)).isoformat(), LOT=f"L{i:03d}")
            for i in range(count)
        )
    )


def test_recent_defaults_to_50_newest_first(use_records: Any) -> None:
    client = use_records(_many(60))

    body = client.get(BASE + "/recent").json()

    assert body["limit"] == 50
    assert body["totalMatching"] == 60
    assert len(body["records"]) == 50
    assert lots(body)[0] == "L059"
    assert lots(body)[-1] == "L010"
    dates = [record["date"] for record in body["records"]]
    assert dates == sorted(dates, reverse=True)


def test_recent_limit_is_configurable(use_records: Any) -> None:
    client = use_records(_many(60))

    body = client.get(BASE + "/recent", params={"limit": 5}).json()

    assert lots(body) == ["L059", "L058", "L057", "L056", "L055"]


def test_same_day_records_keep_source_order(use_records: Any) -> None:
    client = use_records(
        records(
            source_row(DATE="2026-09-01", LOT="first"),
            source_row(DATE="2026-09-01", LOT="second"),
        )
    )

    assert lots(client.get(BASE + "/recent").json()) == ["second", "first"]
    assert lot_ids(client.get(BASE + "/lots").json()) == ["second", "first"]
    assert lot_ids(client.get(BASE + "/trends").json()) == ["first", "second"]


def test_trends_are_oldest_first(use_records: Any) -> None:
    client = use_records(SAMPLE)

    dates = [lot["lastDate"] for lot in client.get(BASE + "/trends").json()["lots"]]

    assert dates == ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]


# Filtering -------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["/recent", "/lots", "/trends"])
def test_product_filter_is_exact(use_records: Any, endpoint: str) -> None:
    client = use_records(SAMPLE)
    key = "records" if endpoint == "/recent" else "lots"

    matched = client.get(BASE + endpoint, params={"product": "PRD-A"}).json()[key]
    unmatched = client.get(BASE + endpoint, params={"product": "prd-a"}).json()[key]

    assert {record["product"] for record in matched} == {"PRD-A"}
    assert len(matched) == 2
    assert unmatched == []


def test_location_filter_does_not_normalize(use_records: Any) -> None:
    client = use_records(SAMPLE)

    title_case = client.get(BASE + "/recent", params={"location": "Silo 1"}).json()
    upper_case = client.get(BASE + "/recent", params={"location": "SILO 1"}).json()

    assert lots(title_case) == ["A260901-01"]
    assert lots(upper_case) == ["B260902-02"]


def test_date_filter_is_inclusive(use_records: Any) -> None:
    client = use_records(SAMPLE)

    body = client.get(
        BASE + "/recent", params={"startDate": "2026-09-02", "endDate": "2026-09-03"}
    ).json()

    assert [record["date"] for record in body["records"]] == ["2026-09-03", "2026-09-02"]


def test_open_ended_date_filters(use_records: Any) -> None:
    client = use_records(SAMPLE)

    after = client.get(BASE + "/trends", params={"startDate": "2026-09-03"}).json()["lots"]
    before = client.get(BASE + "/trends", params={"endDate": "2026-09-01"}).json()["lots"]

    assert [lot["lastDate"] for lot in after] == ["2026-09-03", "2026-09-04"]
    assert [lot["lastDate"] for lot in before] == ["2026-09-01"]


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("a2609", ["A260903-03", "A260901-01"]),  # lot, case-insensitive
        ("26202", [None]),  # campaign number on a record with no lot
        ("  B260902  ", ["B260902-02"]),  # surrounding whitespace ignored
        ("nomatch", []),
    ],
)
def test_search_matches_lot_or_campaign(use_records: Any, term: str, expected: list) -> None:
    client = use_records(SAMPLE)

    assert lots(client.get(BASE + "/recent", params={"search": term}).json()) == expected


def test_filters_combine(use_records: Any) -> None:
    client = use_records(SAMPLE)

    body = client.get(
        BASE + "/recent",
        params={"product": "PRD-A", "location": "Railcar", "startDate": "2026-09-02"},
    ).json()

    assert lots(body) == ["A260903-03"]
    assert body["totalMatching"] == 1


def test_trends_summary_respects_filters(use_records: Any) -> None:
    client = use_records(SAMPLE)

    summary = client.get(BASE + "/trends", params={"product": "PRD-B"}).json()["summary"]

    assert summary["recordCount"] == 2
    assert summary["moistureValueCount"] == 1
    assert summary["avgMoisture"] == pytest.approx(0.6)


# Product + Lot master rows -----------------------------------------------------

LOCATIONS = records(
    source_row(DATE="2026-09-01", PRODUCT="3411", LOT="260932010", Location="PKG/0",
               AvgOfMOISTURE=0.2, AvgOfCOLOR=40.0, AvgOfCombined_BD=0.70),
    source_row(DATE="2026-09-01", PRODUCT="3411", LOT="260932010", Location="SILO/1",
               AvgOfMOISTURE=0.0, AvgOfCOLOR=None, AvgOfCombined_BD=0.74),
    source_row(DATE="2026-09-02", PRODUCT="3411", LOT="OTHER", Location="PKG/0",
               AvgOfMOISTURE=0.9),
    source_row(DATE="2026-09-03", PRODUCT="3411", LOT="260932010", Location="PKG/1",
               AvgOfMOISTURE=None, AvgOfCOLOR=44.0, AvgOfCombined_BD=0.72, CAMPNO="26102"),
    # Same lot text under another product is a different master row.
    source_row(DATE="2026-09-03", PRODUCT="9999", LOT="260932010", Location="PKG/0"),
)  # fmt: skip


def test_location_records_of_a_lot_form_one_master_row(use_records: Any) -> None:
    client = use_records(LOCATIONS)

    body = client.get(BASE + "/trends").json()
    (lot,) = [x for x in body["lots"] if (x["product"], x["lot"]) == ("3411", "260932010")]

    assert body["summary"]["lotCount"] == 3
    assert body["summary"]["recordCount"] == 5
    assert (lot["firstDate"], lot["lastDate"]) == ("2026-09-01", "2026-09-03")
    assert lot["locations"] == ["PKG/0", "PKG/1", "SILO/1"]
    assert lot["campaignNos"] == ["26101", "26102"]
    assert lot["recordCount"] == 3
    assert "records" not in lot


def test_lot_means_use_location_records_counting_zero_and_skipping_null(use_records: Any) -> None:
    client = use_records(LOCATIONS)

    lot = client.get(BASE + "/lots", params={"product": "3411", "search": "2609"}).json()["lots"][0]

    assert (lot["avgMoisture"], lot["moistureValueCount"]) == (pytest.approx(0.1), 2)
    assert (lot["avgColor"], lot["colorValueCount"]) == (pytest.approx(42.0), 2)
    assert (lot["avgCombinedBd"], lot["combinedBdValueCount"]) == (pytest.approx(0.72), 3)


def test_lots_are_newest_first_with_location_records_oldest_first(use_records: Any) -> None:
    client = use_records(LOCATIONS)

    body = client.get(BASE + "/lots").json()

    assert body["totalMatching"] == 3
    assert [(x["product"], x["lot"]) for x in body["lots"]] == [
        ("9999", "260932010"),
        ("3411", "260932010"),
        ("3411", "OTHER"),
    ]
    detail = body["lots"][1]["records"]
    assert [(r["date"], r["location"]) for r in detail] == [
        ("2026-09-01", "PKG/0"),
        ("2026-09-01", "SILO/1"),
        ("2026-09-03", "PKG/1"),
    ]


def test_lots_limit_counts_master_rows(use_records: Any) -> None:
    client = use_records(LOCATIONS)

    body = client.get(BASE + "/lots", params={"limit": 1}).json()

    assert (body["limit"], body["totalMatching"], len(body["lots"])) == (1, 3, 1)


def test_records_without_a_lot_are_not_merged(use_records: Any) -> None:
    client = use_records(
        records(
            source_row(DATE="2026-09-01", LOT=None, Location="PKG/0"),
            source_row(DATE="2026-09-01", LOT=None, Location="PKG/1"),
        )
    )

    body = client.get(BASE + "/trends").json()

    assert body["summary"]["lotCount"] == 2
    assert [lot["recordCount"] for lot in body["lots"]] == [1, 1]


def test_date_filter_limits_the_records_a_lot_is_built_from(use_records: Any) -> None:
    client = use_records(LOCATIONS)

    body = client.get(
        BASE + "/lots", params={"product": "3411", "search": "2609", "endDate": "2026-09-01"}
    ).json()
    (lot,) = body["lots"]

    assert (lot["firstDate"], lot["lastDate"], lot["recordCount"]) == (
        "2026-09-01",
        "2026-09-01",
        2,
    )
    assert lot["avgColor"] == pytest.approx(40.0)


def test_location_filter_keeps_product_lot_master_rows(use_records: Any) -> None:
    client = use_records(LOCATIONS)

    body = client.get(BASE + "/lots", params={"location": "PKG/0"}).json()

    assert body["totalMatching"] == 3
    assert all([r["location"] for r in lot["records"]] == ["PKG/0"] for lot in body["lots"])


# Empty results ---------------------------------------------------------------


def test_no_matches_returns_empty_results(use_records: Any) -> None:
    client = use_records(SAMPLE)
    params = {"product": "DOES-NOT-EXIST"}

    recent = client.get(BASE + "/recent", params=params)
    trends = client.get(BASE + "/trends", params=params)

    assert recent.status_code == 200
    assert recent.json()["records"] == []
    assert recent.json()["totalMatching"] == 0
    assert client.get(BASE + "/lots", params=params).json()["totalMatching"] == 0
    assert trends.json()["lots"] == []
    assert trends.json()["summary"] == {
        "lotCount": 0,
        "recordCount": 0,
        "avgMoisture": None,
        "avgColor": None,
        "avgCombinedBd": None,
        "moistureValueCount": 0,
        "colorValueCount": 0,
        "combinedBdValueCount": 0,
    }


def test_filters_endpoint_with_no_source_data(use_records: Any) -> None:
    client = use_records(())

    body = client.get(BASE + "/filters").json()

    assert body["products"] == []
    assert body["locations"] == []
    assert body["dateRange"] == {"min": None, "max": None}


# Filter options --------------------------------------------------------------


def test_filters_endpoint_returns_distinct_source_values(use_records: Any) -> None:
    client = use_records(SAMPLE + records(source_row(PRODUCT=None, Location=None)))

    body = client.get(BASE + "/filters").json()

    assert body["products"] == ["PRD-A", "PRD-B"]
    assert body["locations"] == ["Railcar", "SILO 1", "Silo 1", "Silo 2"]
    assert body["dateRange"] == {"min": "2026-09-01", "max": "2026-09-04"}


# Validation ------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"startDate": "2026-09-05", "endDate": "2026-09-01"},
        {"startDate": "not-a-date"},
        {"endDate": "2026-13-01"},
        {"limit": 0},
        {"limit": 501},
        {"limit": "ten"},
        {"product": ""},
        {"location": ""},
        {"search": "x" * 101},
        {"unexpected": "value"},
    ],
)
def test_recent_rejects_invalid_parameters(use_records: Any, params: dict[str, Any]) -> None:
    client = use_records(SAMPLE)

    response = client.get(BASE + "/recent", params=params)

    assert response.status_code == 422


def test_trends_rejects_limit_and_inverted_dates(use_records: Any) -> None:
    client = use_records(SAMPLE)

    assert client.get(BASE + "/trends", params={"limit": 5}).status_code == 422
    inverted = {"startDate": "2026-09-05", "endDate": "2026-09-01"}
    assert client.get(BASE + "/trends", params=inverted).status_code == 422


def test_blank_search_is_ignored(use_records: Any) -> None:
    client = use_records(SAMPLE)

    body = client.get(BASE + "/recent", params={"search": "   "}).json()

    assert body["totalMatching"] == 4


def test_lots_rejects_invalid_parameters(use_records: Any) -> None:
    client = use_records(SAMPLE)

    for params in ({"limit": 0}, {"limit": 501}, {"unexpected": "value"}):
        assert client.get(BASE + "/lots", params=params).status_code == 422


def test_moisture_endpoints_are_read_only(use_records: Any) -> None:
    client = use_records(SAMPLE)

    for path in ("/recent", "/lots", "/trends", "/filters"):
        assert client.post(BASE + path).status_code == 405
