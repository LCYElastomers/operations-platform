"""Cost of Quality: records, calculations, COPQ / COQ Matrix summary, estimator, import, API.

Records here are test fixtures built in memory. Monthly figures come from the
reviewed mapping import_templates/quality_cost_of_quality_2026.mapping.json;
the estimator is checked against the values the COPQ workbook calculates for
its example inputs.
"""

import datetime as dt
import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.quality.cost import calculations, estimator, legacy_import, records, service
from app.quality.cost import router as cost_router
from app.quality.cost.classification import CATEGORIES, COQ_CLASSES, is_poor
from app.quality.cost.models import CostMonthlyFact, CostRecord
from app.quality.cost.repository import Option, RecordFilter, RecordRow
from app.quality.cost.schemas import CostRecordCreate, CostRecordUpdate, EstimateRequest

API_ROOT = Path(__file__).resolve().parents[1]
MAPPING = API_ROOT / "import_templates" / "quality_cost_of_quality_2026.mapping.json"
P = Permission
CLOSE = Decimal("1e-9")
TODAY = dt.date(2026, 10, 9)
NOW = dt.datetime(2026, 10, 9, 15, 0, tzinfo=dt.UTC)


def _months(path: Path = MAPPING) -> list[service.MonthInputs]:
    mapping = legacy_import.load_mapping(path)
    return [
        service.MonthInputs(
            year=entry.year,
            month=entry.month,
            **{
                k: v for k, v in legacy_import.month_values(mapping, entry).items() if k != "source"
            },
        )
        for entry in mapping.months
    ]


_ids = iter(range(1, 10_000))


def record(**overrides: Any) -> CostRecord:
    """A fixture record: a confirmed, open internal failure scrap item."""
    values: dict[str, Any] = {
        "id": next(_ids),
        "record_date": dt.date(2026, 3, 10),
        "title": "Fixture scrap",
        "area_id": 1,
        "coq_class": "internal_failure",
        "category_code": "internal_failure.scrap",
        "description": "Fixture record",
        "financial_status": "confirmed",
        "status": "open",
        "source": "manual",
        "version": 1,
        "created_at": NOW,
        "created_by": "fixture",
        "updated_at": NOW,
        "updated_by": "fixture",
        **overrides,
    }
    return CostRecord(**values)


# Classification ------------------------------------------------------------------


def test_every_category_belongs_to_one_class_and_codes_are_unique() -> None:
    codes = [c.code for c in CATEGORIES]

    assert len(codes) == len(set(codes))
    assert all(c.code.startswith(f"{c.coq_class}.") for c in CATEGORIES)
    assert {c.coq_class for c in CATEGORIES} == set(COQ_CLASSES)
    for coq_class in COQ_CLASSES:
        assert f"{coq_class}.other" in codes


def test_only_failure_classes_are_poor_quality_cost() -> None:
    assert [c for c in COQ_CLASSES if is_poor(c)] == ["internal_failure", "external_failure"]


# Record calculations -------------------------------------------------------------


def test_total_is_the_sum_of_entered_components() -> None:
    item = record(material_cost=Decimal("100.10"), labor_cost=Decimal("0.05"), other_cost=0)

    assert calculations.record_total(item) == Decimal("100.15")


def test_no_component_entered_is_an_unknown_cost_not_zero() -> None:
    assert calculations.record_total(record()) is None
    assert calculations.record_total(record(freight_cost=Decimal(0))) == 0
    assert calculations.record_net(record()) is None


def test_net_subtracts_recovered_but_never_avoided() -> None:
    item = record(
        material_cost=Decimal(500), recovered_cost=Decimal(120), avoided_cost=Decimal(1000)
    )

    assert calculations.record_net(item) == Decimal(380)
    assert calculations.record_net(record(material_cost=Decimal(5))) == Decimal(5)


def test_days_open_counts_to_today_or_to_the_date_closed() -> None:
    open_item = record(record_date=dt.date(2026, 9, 9))
    closed = record(
        record_date=dt.date(2026, 9, 9), status="closed", date_closed=dt.date(2026, 9, 19)
    )

    assert calculations.days_open(open_item, TODAY) == 30
    assert calculations.days_open(closed, TODAY) == 10


def test_overdue_needs_a_past_due_date_and_an_open_record() -> None:
    assert calculations.is_overdue(record(due_date=dt.date(2026, 10, 1)), TODAY)
    assert not calculations.is_overdue(record(due_date=TODAY), TODAY)
    assert not calculations.is_overdue(
        record(due_date=dt.date(2026, 10, 1), status="closed", date_closed=TODAY), TODAY
    )


def test_confirmed_and_potential_cost_are_never_combined_silently() -> None:
    items = [
        record(material_cost=Decimal(100), recovered_cost=Decimal(10), avoided_cost=Decimal(7)),
        record(financial_status="closed", labor_cost=Decimal(50)),
        record(financial_status="potential", material_cost=Decimal(1000), recovered_cost=1),
        record(financial_status="validating", material_cost=Decimal(200)),
        record(financial_status="potential"),
    ]
    totals = calculations.totals(items)

    assert totals.confirmed == Decimal(150)
    assert totals.potential == Decimal(1200)
    assert totals.total_exposure == Decimal(1350)
    # Recovered and avoided count from confirmed records only.
    assert (totals.recovered, totals.avoided) == (Decimal(10), Decimal(7))
    assert totals.net == Decimal(140)
    assert (totals.count, totals.confirmed_count, totals.potential_count) == (5, 2, 3)
    assert totals.no_cost_count == 1


def test_totals_of_no_costs_are_unknown() -> None:
    totals = calculations.totals([record(financial_status="potential")])

    assert (totals.confirmed, totals.potential, totals.net) == (None, None, None)


def test_matrix_needs_good_and_poor_for_a_total() -> None:
    full = calculations.matrix(
        {
            "prevention": Decimal(10),
            "appraisal": Decimal(30),
            "internal_failure": Decimal(50),
            "external_failure": None,
        }
    )
    poor_only = calculations.matrix({"internal_failure": Decimal(50)})
    zero = calculations.matrix({"prevention": Decimal(0), "internal_failure": Decimal(0)})

    assert (full.good, full.poor, full.total) == (Decimal(40), Decimal(50), Decimal(90))
    assert full.poor_pct == Decimal(50) / Decimal(90)
    assert (poor_only.good, poor_only.total, poor_only.poor_pct) == (None, None, None)
    assert zero.total == 0 and zero.poor_pct is None


def test_aging_buckets_count_open_records_only() -> None:
    items = [
        record(record_date=TODAY - dt.timedelta(days=5), material_cost=Decimal(1)),
        record(record_date=TODAY - dt.timedelta(days=45)),
        record(record_date=TODAY - dt.timedelta(days=200), material_cost=Decimal(2)),
        record(
            record_date=TODAY - dt.timedelta(days=300),
            status="closed",
            date_closed=TODAY,
        ),
    ]
    buckets = calculations.aging(items, TODAY)

    assert [b.count for b in buckets] == [1, 1, 0, 1]
    assert buckets[0].exposure == Decimal(1) and buckets[1].exposure is None


# Summary: COPQ and the COQ Matrix from the same records ---------------------------


def _summary(items: list[CostRecord], **kwargs: Any) -> Any:
    options = {
        "year": 2026,
        "available_years": [2026],
        "from_month": None,
        "through_month": None,
        "today": TODAY,
        **kwargs,
    }
    return service.summary(items, _months(), **options)


def _mixed() -> list[CostRecord]:
    return [
        record(record_date=dt.date(2026, 1, 5), material_cost=Decimal(1000)),
        record(
            record_date=dt.date(2026, 1, 20),
            coq_class="external_failure",
            category_code="external_failure.credit",
            customer_cost=Decimal(400),
            recovered_cost=Decimal(100),
        ),
        record(
            record_date=dt.date(2026, 2, 3),
            coq_class="prevention",
            category_code="prevention.training",
            labor_cost=Decimal(300),
            status="closed",
            date_closed=dt.date(2026, 2, 3),
        ),
        record(
            record_date=dt.date(2026, 2, 9),
            coq_class="appraisal",
            category_code="appraisal.calibration",
            testing_cost=Decimal(100),
        ),
        record(
            record_date=dt.date(2026, 2, 15),
            financial_status="potential",
            category_code="internal_failure.rework",
            labor_cost=Decimal(5000),
        ),
    ]


def test_matrix_and_copq_come_from_the_same_records() -> None:
    body = _summary(_mixed())

    assert (body.matrix.good, body.matrix.poor) == (Decimal(400), Decimal(1400))
    assert body.matrix.total == Decimal(1800)
    assert body.matrix.poor_pct == Decimal(1400) / Decimal(1800)
    assert body.copq.figures.confirmed == body.matrix.poor
    assert body.copq.figures.potential == body.matrix.poor_potential == Decimal(5000)
    assert body.matrix.good_potential is None
    assert body.copq.figures.recovered == Decimal(100)
    assert body.copq.figures.net == Decimal(1300)
    classes = {c.code: c for c in body.classes}
    assert classes["internal_failure"].figures.confirmed == Decimal(1000)
    assert classes["prevention"].share_of_total == Decimal(300) / Decimal(1800)


def test_period_defaults_to_the_latest_month_with_a_record() -> None:
    body = _summary(_mixed())

    assert (body.from_month, body.through_month, body.latest_month) == (1, 2, 2)
    assert len(body.months) == 12
    assert body.months[0].poor == Decimal(1400) and body.months[1].good == Decimal(400)
    assert body.months[1].poor_potential == Decimal(5000) and body.months[1].poor is None
    assert body.months[2].record_count == 0 and body.months[2].poor is None


def test_period_limits_every_figure() -> None:
    body = _summary(_mixed(), from_month=2, through_month=2)

    assert body.matrix.poor is None and body.matrix.good == Decimal(400)
    assert body.copq.figures.count == 1
    assert {c.code for c in body.categories} == {
        "prevention.training",
        "appraisal.calibration",
        "internal_failure.rework",
    }


def test_percent_of_sales_and_cost_per_pound_use_the_monthly_denominators() -> None:
    body = _summary(_mixed())

    sales = Decimal("10259998") + Decimal("11506662")
    assert body.copq.sales_revenue == sales
    assert body.copq.copq_pct_of_sales == Decimal(1400) / sales
    production = sum((m.total_production_lbs for m in _months()), Decimal(0))
    assert body.copq.internal_cost_per_lb == Decimal(1000) / production
    assert body.months[0].copq_pct_of_sales == Decimal(1400) / Decimal("10259998")


def test_categories_are_in_pareto_order_with_a_cumulative_share_of_copq() -> None:
    items = [
        record(material_cost=Decimal(100)),
        record(category_code="internal_failure.rework", labor_cost=Decimal(300)),
        record(
            coq_class="external_failure",
            category_code="external_failure.return",
            freight_cost=Decimal(100),
        ),
        record(coq_class="prevention", category_code="prevention.training", labor_cost=Decimal(50)),
    ]
    categories = _summary(items).categories

    confirmed = [c.figures.confirmed for c in categories]
    assert confirmed == sorted(confirmed, reverse=True)
    poor = [c for c in categories if is_poor(c.coq_class)]
    assert poor[-1].cumulative_share_of_poor == Decimal(1)
    assert (
        next(c for c in categories if c.coq_class == "prevention").cumulative_share_of_poor is None
    )
    rework = next(c for c in categories if c.code == "internal_failure.rework")
    assert rework.share_of_class == Decimal(300) / Decimal(400)
    assert rework.label == "Rework"


def test_without_good_cost_the_total_and_poor_percent_are_not_recorded() -> None:
    body = _summary([record(material_cost=Decimal(10))])

    assert body.matrix.poor == Decimal(10)
    assert (body.matrix.good, body.matrix.total, body.matrix.poor_pct) == (None, None, None)
    assert any("Prevention or Appraisal" in c.message for c in body.data_checks)


def test_data_checks_flag_missing_costs_potential_records_and_missing_sales() -> None:
    items = [
        record(record_date=dt.date(2026, 5, 1)),
        record(record_date=dt.date(2026, 5, 2), material_cost=Decimal(1)),
        record(record_date=dt.date(2026, 5, 3), financial_status="validating"),
    ]
    messages = " ".join(c.message for c in _summary(items).data_checks)

    assert "2 records have no cost entered" in messages
    assert "1 record has" in messages and "potential exposure" in messages
    assert "Sales revenue is not reported for May" in messages


def test_no_records_at_all() -> None:
    body = _summary([], year=None, available_years=[])

    assert body.year is None and body.latest_month is None
    assert body.copq.figures.count == 0 and body.matrix.poor is None
    assert all(m.record_count == 0 for m in body.months)


def test_aging_covers_open_failure_records_only() -> None:
    items = [
        record(record_date=dt.date(2026, 10, 1)),
        record(coq_class="appraisal", category_code="appraisal.audit"),
    ]
    body = _summary(items)

    assert sum(b.count for b in body.aging) == 1
    assert body.copq.open_count == 1


# Record validation -----------------------------------------------------------------


class _Areas:
    def areas(self) -> list[Option]:
        return [Option(1, "100", "100", True), Option(2, "old", "Old", False)]


def _fields(**overrides: Any) -> CostRecordCreate:
    data: dict[str, Any] = {
        "recordDate": "2026-10-01",
        "title": "Off-spec lot",
        "areaId": 1,
        "coqClass": "internal_failure",
        "categoryCode": "internal_failure.scrap",
        "description": "Lot scrapped after a moisture failure.",
        "financialStatus": "potential",
        "status": "open",
        **overrides,
    }
    return CostRecordCreate.model_validate(data)


def _validated(fields: CostRecordCreate, current: CostRecord | None = None) -> Any:
    return records._validated(_Areas(), fields, today=TODAY, current=current)  # type: ignore[arg-type]


def test_a_potential_record_needs_no_cost() -> None:
    values, references = _validated(_fields())

    assert values["material_cost"] is None and values["financial_status"] == "potential"
    assert references == ()


def test_text_is_trimmed_and_blank_optional_text_is_not_entered() -> None:
    values, _ = _validated(_fields(title="  Lot 12  ", product="  ", owner=" A. Smith "))

    assert values["title"] == "Lot 12"
    assert values["product"] is None and values["owner"] == "A. Smith"


@pytest.mark.parametrize(
    ("overrides", "error", "field"),
    [
        ({"title": "  "}, "blank_title", "title"),
        ({"description": " "}, "blank_description", "description"),
        ({"areaId": None}, "area_required", "areaId"),
        ({"areaId": 2}, "invalid_area", "areaId"),
        ({"areaId": 99}, "invalid_area", "areaId"),
        ({"recordDate": "2026-10-10"}, "future_date", "recordDate"),
        ({"recordDate": "1999-12-31"}, "invalid_date", "recordDate"),
        ({"categoryCode": "external_failure.credit"}, "invalid_category", "categoryCode"),
        ({"categoryCode": "internal_failure.unknown"}, "invalid_category", "categoryCode"),
        ({"status": "closed"}, "date_closed_required", "dateClosed"),
        (
            {"status": "closed", "dateClosed": "2026-09-30"},
            "closed_before_date",
            "dateClosed",
        ),
        (
            {"status": "closed", "dateClosed": "2026-10-10"},
            "future_date_closed",
            "dateClosed",
        ),
        ({"dateClosed": "2026-10-02"}, "date_closed_not_closed", "dateClosed"),
        ({"dueDate": "2026-09-01"}, "due_before_date", "dueDate"),
        (
            {"references": [{"type": "corrective_action", "key": "CAR-1"}]},
            "invalid_reference",
            "references",
        ),
    ],
)
def test_record_rules(overrides: dict[str, Any], error: str, field: str) -> None:
    with pytest.raises(records.RecordRuleError) as raised:
        _validated(_fields(**overrides))

    assert (raised.value.error, raised.value.field) == (error, field)


def test_an_unchanged_inactive_area_stays_valid() -> None:
    values, _ = _validated(_fields(areaId=2), current=record(area_id=2))

    assert values["area_id"] == 2


def test_an_imported_record_may_keep_no_area() -> None:
    imported = record(area_id=None, source="legacy_import")

    assert _validated(_fields(areaId=None), current=imported)[0]["area_id"] is None


def test_closed_record_with_a_date_closed_is_valid() -> None:
    values, _ = _validated(_fields(status="closed", dateClosed="2026-10-05"))

    assert values["date_closed"] == dt.date(2026, 10, 5)


def test_references_are_trimmed_and_deduplicated() -> None:
    refs = [
        {"type": "reference", "key": " QN-12 "},
        {"type": "reference", "key": "QN-12"},
        {"type": "reference", "key": "  "},
    ]
    _, references = _validated(_fields(references=refs))

    assert [(r.type, r.key) for r in references] == [("reference", "QN-12")]


@pytest.mark.parametrize(
    "overrides",
    [
        {"materialCost": "-1"},
        {"materialCost": "1.12345"},
        {"coqClass": "good"},
        {"financialStatus": "estimated"},
        {"status": "done"},
        {"unknown": 1},
        {"title": "x" * 201},
    ],
)
def test_schema_rejects_invalid_input(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _fields(**overrides)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("QC-00042", 42), ("qc42", 42), (" QC-7 ", 7), ("Q-42", None), ("42", None), ("", None)],
)
def test_record_numbers(text: str, expected: int | None) -> None:
    assert records.parse_record_number(text) == expected


def test_record_number_is_derived_from_the_id() -> None:
    assert records.record_number(42) == "QC-00042"


# Monthly calculations (the workbook import) ------------------------------------------


def test_month_costs_match_the_workbook_totals() -> None:
    january, february = (service.month_cost(m) for m in _months())

    assert january.internal_failure == Decimal("25435.17")
    assert january.external_failure == Decimal("26720")
    assert february.elements["scrap"] == Decimal("16851.25")
    assert february.elements["offspec"] == Decimal("4140.5")
    assert february.external_failure == Decimal("2800")


def test_blank_off_spec_is_not_reported_not_zero() -> None:
    january = service.month_cost(_months()[0])

    assert january.elements["offspec"] is None


# Estimator -----------------------------------------------------------------------


WORKBOOK_EXAMPLE: dict[str, Any] = {
    "product": "3411",
    "downtime": {"downtimeHours": 48},
    "lowerProduction": {"flowRateLbPerHour": 9500, "hours": 48},
    "scrap": {"quantityLbs": 100000},
    "cGrade": {"quantityLbs": 100000},
    "rework": {
        "productionRateReductionLbPerHour": 1000,
        "reworkingRateLbPerHour": 1000,
        "quantityLbs": 200000,
        "packageType": "Bags",
        "packageLoadLbPerPiece": 30,
    },
    "repack": {
        "quantityLbs": 20000,
        "packageType": "Bags",
        "packageLoadLbPerPiece": 30,
        "extraPersons": 1,
        "overtimeHoursPerPerson": 24,
        "payRateUsdPerHour": 35,
    },
}

# Values the workbook calculates for its example inputs (kUSD).
WORKBOOK_RESULTS = {
    "downtime": Decimal("115"),
    "lower_production": Decimal("110.9612"),
    "scrap": Decimal("77.51"),
    "c_grade": Decimal("33.95"),
    "rework": Decimal("58.084848484848486"),
    "repack": Decimal("1.42696"),
}


def _estimate(data: dict[str, Any]) -> Any:
    return estimator.estimate(EstimateRequest.model_validate(data))


def test_estimator_reproduces_each_workbook_line() -> None:
    result = _estimate(WORKBOOK_EXAMPLE)
    lines = {line.code: line.total_kusd for line in result.lines}

    assert set(lines) == set(WORKBOOK_RESULTS)
    for code, expected in WORKBOOK_RESULTS.items():
        assert abs(lines[code] - expected) < CLOSE, code


def test_estimator_reproduces_the_workbook_summary_total() -> None:
    # The workbook's example selects downtime, scrap, C-grade and rework.
    selected = {k: v for k, v in WORKBOOK_EXAMPLE.items() if k not in ("lowerProduction", "repack")}
    result = _estimate(selected)

    assert abs(result.total_kusd - Decimal("284.54484848484844")) < CLOSE
    assert result.total_usd == result.total_kusd * 1000


def test_rework_shows_but_does_not_add_the_steam_and_power_cost() -> None:
    rework = next(line for line in _estimate(WORKBOOK_EXAMPLE).lines if line.code == "rework")
    energy = next(s for s in rework.steps if s.label.startswith("Steam and power"))

    assert abs(energy.value - Decimal("3.0315789473684203")) < CLOSE
    assert "not included" in rework.formula


def test_repack_rounds_pieces_like_the_workbook() -> None:
    repack = next(line for line in _estimate(WORKBOOK_EXAMPLE).lines if line.code == "repack")

    assert next(s for s in repack.steps if s.label == "Pieces").value == Decimal(667)


def test_package_price_follows_the_package_type() -> None:
    def packaging(package_type: str) -> Decimal:
        data = {**WORKBOOK_EXAMPLE["repack"], "packageType": package_type, "extraPersons": 0}
        return _estimate({"repack": data}).lines[0].total_kusd

    assert packaging("Box") == Decimal(667) * 32 / 1000
    assert packaging("Single sacks") == packaging("Double stack supersacks") == Decimal("8.004")


def test_lower_production_above_the_standard_rate_is_not_a_negative_cost() -> None:
    result = _estimate(
        {"product": "3411", "lowerProduction": {"flowRateLbPerHour": 20000, "hours": 24}}
    )

    assert result.lines[0].total_kusd == 0
    assert result.warnings


def test_nothing_selected_is_a_zero_estimate() -> None:
    result = _estimate({})

    assert result.lines == [] and result.total_kusd == 0


@pytest.mark.parametrize("product", [None, "3142", "9999"])
def test_line_rate_lines_need_a_known_product(product: str | None) -> None:
    with pytest.raises(estimator.EstimateError):
        _estimate({"product": product, "downtime": {"downtimeHours": 1}})


def test_reference_lists_the_workbook_products_and_assumptions() -> None:
    reference = estimator.reference_response()

    assert len(reference.products) == 18
    assert "3142" not in {p.code for p in reference.products}
    assert {p.code: p.standard_rate_mt_per_day for p in reference.products}["3546"] == 189
    assert any(a.label == "Gross margin" and a.value == 75 for a in reference.assumptions)
    assert reference.guidance and reference.notes


# Import --------------------------------------------------------------------------


def test_reviewed_mapping_recalculates_to_the_workbook_totals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert legacy_import.run("check", MAPPING) == 0
    out = capsys.readouterr().out
    assert "MISMATCH" not in out
    assert "2026-01" in out and "2026-02" in out


def test_mapping_holds_only_months_with_figures() -> None:
    mapping = legacy_import.load_mapping(MAPPING)

    assert [(m.year, m.month) for m in mapping.months] == [(2026, 1), (2026, 2)]
    assert mapping.months[0].offspec_produced_lbs.value is None


def _altered(tmp_path: Path, change: Any) -> Path:
    data = json.loads(MAPPING.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_workbook_total_mismatch_blocks_the_import(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def change(data: dict[str, Any]) -> None:
        data["months"][1]["legacyCustomerComplaintCost"]["value"] = "2900"

    assert legacy_import.run("check", _altered(tmp_path, change)) == 1
    assert "MISMATCH" in capsys.readouterr().out


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["months"].append(d["months"][0]),
        lambda d: d["months"][0]["scrapProducedLbs"].update(value="-1"),
        lambda d: d["months"][0]["scrapProducedLbs"].update(sourceCell="D3"),
        lambda d: d["months"][0].update(month=13),
        lambda d: d["months"][0].update(extra=1),
    ],
)
def test_invalid_mappings_are_rejected(tmp_path: Path, change: Any) -> None:
    assert legacy_import.run("check", _altered(tmp_path, change)) == 2


def test_a_month_without_figures_is_rejected(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        for key, cell in data["months"][0].items():
            if isinstance(cell, dict) and not key.startswith("legacy"):
                cell["value"] = None

    assert legacy_import.run("check", _altered(tmp_path, change)) == 2


def _lines() -> list[legacy_import.RecordLine]:
    mapping = legacy_import.load_mapping(MAPPING)
    return [line for e in mapping.months for line in legacy_import.record_lines(mapping, e, TODAY)]


def test_reported_cost_lines_become_confirmed_closed_records() -> None:
    lines = {line.source_key: line for line in _lines()}

    # January off-spec is blank in the workbook: no record, not a $0 record.
    assert sorted(lines) == [
        "coq-workbook/2026-01/customer-complaints",
        "coq-workbook/2026-01/scrap",
        "coq-workbook/2026-02/customer-complaints",
        "coq-workbook/2026-02/offspec",
        "coq-workbook/2026-02/scrap",
    ]
    scrap = lines["coq-workbook/2026-02/scrap"].values
    assert scrap["material_cost"] == Decimal("16851.25")
    assert (scrap["coq_class"], scrap["category_code"]) == (
        "internal_failure",
        "internal_failure.scrap",
    )
    assert scrap["record_date"] == dt.date(2026, 2, 1)
    assert scrap["date_closed"] == dt.date(2026, 2, 28)
    assert (scrap["financial_status"], scrap["status"], scrap["area_id"]) == (
        "confirmed",
        "closed",
        None,
    )


def test_converted_records_add_up_to_the_workbook_totals() -> None:
    by_month: dict[str, Decimal] = {}
    for line in _lines():
        month = line.source_key.split("/")[1]
        cost = calculations.record_total(CostRecord(**line.values))
        by_month[month] = by_month.get(month, Decimal(0)) + (cost or 0)

    assert by_month == {"2026-01": Decimal("52155.17"), "2026-02": Decimal("23791.75")}


def test_complaint_record_keeps_the_lines_as_components() -> None:
    january = next(line for line in _lines() if line.source_key.endswith("01/customer-complaints"))

    assert january.values["coq_class"] == "external_failure"
    assert "return freight $2,350.00" in january.values["description"]
    assert january.values["freight_cost"] is not None
    assert all("!" in cell for cell in january.cells)


def _stored(path: Path = MAPPING) -> dict[tuple[int, int], CostMonthlyFact]:
    mapping = legacy_import.load_mapping(path)
    return {
        (e.year, e.month): CostMonthlyFact(
            reporting_year=e.year, reporting_month=e.month, **legacy_import.month_values(mapping, e)
        )
        for e in mapping.months
    }


def _imported() -> dict[str, CostRecord]:
    return {line.source_key: CostRecord(**line.values) for line in _lines()}


def test_plan_inserts_months_and_records_and_is_idempotent() -> None:
    mapping = legacy_import.load_mapping(MAPPING)

    first = legacy_import.plan_import({}, mapping, {}, today=TODAY)
    again = legacy_import.plan_import(_stored(), mapping, _imported(), today=TODAY)

    assert [(e.year, e.month) for e in first.inserts] == [(2026, 1), (2026, 2)]
    assert len(first.record_inserts) == 5
    assert again.empty and not again.blocked
    assert len(again.records_unchanged) == 5


def test_months_already_stored_still_plan_their_records() -> None:
    plan = legacy_import.plan_import(
        _stored(), legacy_import.load_mapping(MAPPING), {}, today=TODAY
    )

    assert plan.inserts == [] and len(plan.record_inserts) == 5 and not plan.empty


def test_plan_blocks_a_stored_month_or_record_that_differs() -> None:
    stored = _stored()
    stored[(2026, 2)].sales_revenue = Decimal("1")
    imported = _imported()
    imported["coq-workbook/2026-02/scrap"].material_cost = Decimal(1)

    plan = legacy_import.plan_import(
        stored, legacy_import.load_mapping(MAPPING), imported, today=TODAY
    )

    assert [(y, m, f) for y, m, f, _, _ in plan.differing] == [(2026, 2, "sales_revenue")]
    assert [(k, f) for k, f, _, _ in plan.records_differing] == [
        ("coq-workbook/2026-02/scrap", "material_cost")
    ]
    assert plan.blocked


def test_edits_outside_the_imported_fields_do_not_block_a_rerun() -> None:
    imported = _imported()
    imported["coq-workbook/2026-02/scrap"].owner = "Quality lead"
    imported["coq-workbook/2026-02/scrap"].status = "monitoring"

    plan = legacy_import.plan_import(
        _stored(), legacy_import.load_mapping(MAPPING), imported, today=TODAY
    )

    assert not plan.blocked


# API -----------------------------------------------------------------------------


class _Memory:
    """In-memory stand-in for CostRepository (fixture records only)."""

    def __init__(self) -> None:
        self.records: dict[int, CostRecord] = {}
        self.refs: dict[int, tuple[Any, ...]] = {}
        self.audits: list[Any] = []
        self.next_id = 1

    def areas(self) -> list[Option]:
        return [Option(1, "100", "100", True)]

    def distinct_values(self, column: str) -> list[str]:
        return sorted({getattr(r, column) for r in self.records.values() if getattr(r, column)})

    def facts(self) -> dict[tuple[int, int], Any]:
        return {
            (m.year, m.month): CostMonthlyFact(
                reporting_year=m.year,
                reporting_month=m.month,
                **{k: v for k, v in m.__dict__.items() if k not in ("year", "month")},
            )
            for m in _months()
        }

    def record_years(self) -> list[int]:
        return sorted({r.record_date.year for r in self.records.values()}, reverse=True)

    def _row(self, item: CostRecord) -> RecordRow:
        return RecordRow(item, "100" if item.area_id else None, self.refs.get(item.id, ()))

    def search(
        self, criteria: RecordFilter, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[RecordRow], int]:
        found = [
            r
            for r in self.records.values()
            if (not criteria.coq_classes or r.coq_class in criteria.coq_classes)
            and (criteria.date_from is None or r.record_date >= criteria.date_from)
            and (criteria.date_to is None or r.record_date <= criteria.date_to)
            and (not criteria.statuses or r.status in criteria.statuses)
            and (criteria.search_id is None or r.id == criteria.search_id)
        ]
        return [self._row(r) for r in found], len(found)

    def get(self, record_id: int) -> RecordRow | None:
        item = self.records.get(record_id)
        return None if item is None else self._row(item)

    def lock_record(self, record_id: int) -> CostRecord | None:
        return self.records.get(record_id)

    def references_of(self, record_id: int) -> tuple[Any, ...]:
        return self.refs.get(record_id, ())

    def insert_record(self, values: dict[str, Any], *, actor_id: str, at: dt.datetime) -> int:
        record_id = self.next_id
        self.next_id += 1
        self.records[record_id] = CostRecord(
            id=record_id,
            **values,
            version=1,
            created_at=at,
            created_by=actor_id,
            updated_at=at,
            updated_by=actor_id,
        )
        return record_id

    def update_record(
        self, record_id: int, values: dict[str, Any], *, version: int, actor_id: str, at: Any
    ) -> None:
        item = self.records[record_id]
        for key, value in values.items():
            setattr(item, key, value)
        item.version, item.updated_by, item.updated_at = version + 1, actor_id, at

    def replace_references(self, record_id: int, references: Any, **_: Any) -> None:
        self.refs[record_id] = tuple(references)

    def record_audit(self, **kwargs: Any) -> None:
        self.audits.append(kwargs)

    def history(self, entity_type: str, entity_key: str) -> list[Any]:
        return []

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture
def memory() -> _Memory:
    return _Memory()


@pytest.fixture
def api(memory: _Memory) -> Iterator[Any]:
    def make(*permissions: Permission) -> TestClient:
        app = create_app()
        app.dependency_overrides[cost_router.cost_repository] = lambda: memory
        app.dependency_overrides[get_user_principal] = lambda: UserPrincipal(
            "tester", authenticated=True, granted=frozenset(permissions)
        )
        return TestClient(app)

    yield make


NEW_RECORD: dict[str, Any] = {
    "recordDate": "2026-03-04",
    "title": "Rework of lot 4411",
    "areaId": 1,
    "coqClass": "internal_failure",
    "categoryCode": "internal_failure.rework",
    "description": "Fixture: lot reworked after a colour failure.",
    "laborCost": "1200.50",
    "materialCost": "0",
    "financialStatus": "confirmed",
    "status": "open",
    "owner": "Fixture owner",
    "references": [{"type": "reference", "key": "QN-0001"}],
}


@pytest.mark.parametrize("path", ["summary", "estimator", "records", "records/options"])
def test_reading_requires_quality_cost_view(api: Any, path: str) -> None:
    url = f"/api/v1/quality/cost/{path}"
    assert api(P.QUALITY_COST_VIEW).get(url).status_code == 200
    assert api(P.QUALITY_VIEW).get(url).status_code == 200
    assert api(P.SAFETY_MANAGE).get(url).status_code == 403
    assert api().get(url).status_code == 403


def test_adding_requires_quality_cost_edit(api: Any) -> None:
    url = "/api/v1/quality/cost/records"
    assert api(P.QUALITY_COST_VIEW).post(url, json=NEW_RECORD).status_code == 403
    assert api(P.QUALITY_VIEW).post(url, json=NEW_RECORD).status_code == 403
    assert api(P.QUALITY_COST_EDIT).post(url, json=NEW_RECORD).status_code == 201
    assert api(P.QUALITY_EDIT).post(url, json=NEW_RECORD).status_code == 201
    assert api(P.QUALITY_MANAGE).post(url, json=NEW_RECORD).status_code == 201


def test_options_carry_the_central_classification(api: Any) -> None:
    body = api(P.QUALITY_COST_VIEW).get("/api/v1/quality/cost/records/options").json()

    assert [c["code"] for c in body["classes"]] == list(COQ_CLASSES)
    assert [c["qualityGroup"] for c in body["classes"]] == ["good", "good", "poor", "poor"]
    internal = next(c for c in body["classes"] if c["code"] == "internal_failure")
    assert {"code": "internal_failure.scrap", "label": "Scrap"} in internal["categories"]
    assert [s["code"] for s in body["financialStatuses"] if s["confirmed"]] == [
        "confirmed",
        "closed",
    ]
    assert body["costComponents"][0] == {"field": "materialCost", "label": "Material"}
    assert body["canEdit"] is False


def test_create_returns_derived_figures_and_audits(api: Any, memory: _Memory) -> None:
    response = api(P.QUALITY_COST_EDIT).post("/api/v1/quality/cost/records", json=NEW_RECORD)

    assert response.status_code == 201, response.text
    body = response.json()["record"]
    assert body["recordNumber"] == "QC-00001"
    assert body["totalCost"] == "1200.5" and body["netCost"] == "1200.5"
    assert body["materialCost"] == "0" and body["freightCost"] is None
    assert body["qualityGroup"] == "poor" and body["costConfirmed"] is True
    assert body["categoryLabel"] == "Rework" and body["areaName"] == "100"
    assert body["createdBy"] == "tester" and body["version"] == 1
    assert body["references"] == [
        {"type": "reference", "typeLabel": "Reference / document number", "key": "QN-0001",
         "label": None}
    ]  # fmt: skip
    assert "sourceReference" not in body and "sourceKey" not in body
    (audit,) = memory.audits
    (change,) = audit["changes"]
    assert change.entity_key == "cost-records/1" and change.action == "create"
    assert change.new_value["labor_cost"] == "1200.5"
    assert change.new_value["references"] == [
        {"type": "reference", "key": "QN-0001", "label": None}
    ]


def test_rule_errors_name_the_field(api: Any) -> None:
    response = api(P.QUALITY_COST_EDIT).post(
        "/api/v1/quality/cost/records", json={**NEW_RECORD, "status": "closed"}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "dateClosed"


def test_update_checks_the_version_and_audits_the_change(api: Any, memory: _Memory) -> None:
    client = api(P.QUALITY_COST_EDIT)
    client.post("/api/v1/quality/cost/records", json=NEW_RECORD)
    changed = {
        **NEW_RECORD,
        "version": 1,
        "status": "closed",
        "dateClosed": "2026-03-20",
        "recoveredCost": "200",
    }

    response = client.put("/api/v1/quality/cost/records/1", json=changed)
    stale = client.put("/api/v1/quality/cost/records/1", json=changed)
    missing = client.put("/api/v1/quality/cost/records/9", json=changed)

    assert response.status_code == 200, response.text
    body = response.json()["record"]
    assert body["version"] == 2 and body["status"] == "closed"
    assert body["netCost"] == "1000.5" and body["daysOpen"] == 16
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["version"] == 2
    assert missing.status_code == 404
    update = memory.audits[-1]["changes"][0]
    assert update.action == "update"
    assert update.old_value["status"] == "open" and update.new_value["status"] == "closed"


def test_an_unchanged_update_writes_nothing(api: Any, memory: _Memory) -> None:
    client = api(P.QUALITY_COST_EDIT)
    client.post("/api/v1/quality/cost/records", json=NEW_RECORD)

    response = client.put("/api/v1/quality/cost/records/1", json={**NEW_RECORD, "version": 1})

    assert response.json()["record"]["version"] == 1
    assert len(memory.audits) == 1


def test_records_search_by_number_and_open_filter(api: Any) -> None:
    client = api(P.QUALITY_COST_EDIT)
    client.post("/api/v1/quality/cost/records", json=NEW_RECORD)
    client.post(
        "/api/v1/quality/cost/records",
        json={**NEW_RECORD, "status": "closed", "dateClosed": "2026-03-05"},
    )

    by_number = client.get("/api/v1/quality/cost/records?search=QC-00002").json()
    open_only = client.get("/api/v1/quality/cost/records?open=true").json()

    assert [r["id"] for r in by_number["records"]] == [2]
    assert [r["id"] for r in open_only["records"]] == [1]
    assert by_number["canEdit"] is True


def test_summary_from_entered_records(api: Any) -> None:
    client = api(P.QUALITY_COST_EDIT)
    client.post("/api/v1/quality/cost/records", json=NEW_RECORD)
    client.post(
        "/api/v1/quality/cost/records",
        json={
            **NEW_RECORD,
            "coqClass": "prevention",
            "categoryCode": "prevention.training",
            "laborCost": "300",
        },
    )

    body = client.get("/api/v1/quality/cost/summary").json()
    poor_only = client.get("/api/v1/quality/cost/summary?poorOnly=true").json()
    none = client.get("/api/v1/quality/cost/summary?poorOnly=true&coqClass=appraisal").json()

    assert body["year"] == 2026 and body["throughMonth"] == 3
    assert body["matrix"]["poor"] == "1200.5" and body["matrix"]["good"] == "300"
    assert body["matrix"]["total"] == "1500.5"
    assert poor_only["matrix"]["good"] is None
    assert poor_only["copq"]["figures"]["confirmed"] == "1200.5"
    assert none["copq"]["figures"]["count"] == 0
    decimals = [body["matrix"]["poorPct"], body["copq"]["copqPctOfSales"]]
    assert not [d for d in decimals if d is not None and "E" in d.upper()]


def test_summary_with_no_records(api: Any) -> None:
    body = api(P.QUALITY_COST_VIEW).get("/api/v1/quality/cost/summary").json()

    assert body["year"] is None and body["availableYears"] == []
    assert body["copq"]["figures"]["count"] == 0


@pytest.mark.parametrize(
    "query", ["year=1999", "from=0", "through=13", "year=abc", "coqClass=good", "areaId=0"]
)
def test_summary_validates_its_filters(api: Any, query: str) -> None:
    assert api(P.QUALITY_COST_VIEW).get(f"/api/v1/quality/cost/summary?{query}").status_code == 422


@pytest.mark.parametrize("path", ["summary", "estimator", "records", "records/options"])
def test_responses_carry_no_workbook_cell_coordinates(api: Any, path: str) -> None:
    body = api(P.QUALITY_COST_VIEW).get(f"/api/v1/quality/cost/{path}").text

    assert "sourceCell" not in body and "sourceReference" not in body and "!" not in body
    # R0 is the COPQ workbook's revision, not a cell.
    cells = [c for c in re.findall(r"\b[A-Z]{1,3}[0-9]{1,5}\b", body) if c != "R0"]
    assert not cells, cells


def test_estimate_requires_the_permission(api: Any) -> None:
    url = "/api/v1/quality/cost/estimate"
    assert api().post(url, json={}).status_code == 403
    assert api(P.QUALITY_COST_VIEW).post(url, json={}).status_code == 200


def test_estimate_endpoint_matches_the_workbook(api: Any) -> None:
    response = api(P.QUALITY_COST_VIEW).post("/api/v1/quality/cost/estimate", json=WORKBOOK_EXAMPLE)

    assert response.status_code == 200, response.text
    lines = {line["code"]: Decimal(line["totalKusd"]) for line in response.json()["lines"]}
    assert abs(lines["downtime"] - 115) < CLOSE


@pytest.mark.parametrize(
    "payload",
    [
        {"product": "9999", "downtime": {"downtimeHours": 1}},
        {"downtime": {"downtimeHours": 1}},
        {"scrap": {"quantityLbs": -1}},
        {"downtime": {"downtimeHours": 9000}, "product": "3411"},
        {"rework": {**WORKBOOK_EXAMPLE["rework"], "reworkingRateLbPerHour": 0}, "product": "3411"},
        {"repack": {**WORKBOOK_EXAMPLE["repack"], "packageType": "Crate"}},
        {"scrap": {"quantityLbs": 1}, "unknown": True},
    ],
)
def test_estimate_rejects_invalid_inputs(api: Any, payload: dict[str, Any]) -> None:
    response = api(P.QUALITY_COST_VIEW).post("/api/v1/quality/cost/estimate", json=payload)

    assert response.status_code == 422, response.text


def test_update_schema_needs_a_version() -> None:
    with pytest.raises(ValueError):
        CostRecordUpdate.model_validate({k: v for k, v in NEW_RECORD.items()})
