"""Cost of Poor Quality and Cost of Quality Matrix: calculations, estimator, import, API.

Monthly figures come from the reviewed mapping
import_templates/quality_cost_of_quality_2026.mapping.json; the estimator is
checked against the values the COPQ workbook calculates for its example inputs.
"""

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
from app.quality.cost import estimator, legacy_import, service
from app.quality.cost import router as cost_router
from app.quality.cost.models import CostMonthlyFact
from app.quality.cost.schemas import EstimateRequest

API_ROOT = Path(__file__).resolve().parents[1]
MAPPING = API_ROOT / "import_templates" / "quality_cost_of_quality_2026.mapping.json"
P = Permission
CLOSE = Decimal("1e-9")


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


def _summary(**kwargs: Any) -> Any:
    options = {"year": None, "from_month": None, "through_month": None, **kwargs}
    return service.summary(_months(), **options)


# Monthly calculations ------------------------------------------------------------


def test_month_costs_match_the_workbook_totals() -> None:
    january, february = (service.month_cost(m) for m in _months())

    assert january.internal_failure == Decimal("25435.17")
    assert january.external_failure == Decimal("26720")
    assert january.copq == Decimal("52155.17")
    assert february.elements["scrap"] == Decimal("16851.25")
    assert february.elements["offspec"] == Decimal("4140.5")
    assert february.internal_failure == Decimal("20991.75")
    assert february.external_failure == Decimal("2800")


def test_blank_off_spec_is_not_reported_not_zero() -> None:
    january = service.month_cost(_months()[0])

    assert january.elements["offspec"] is None
    assert january.elements["return_freight"] == Decimal("2350")


def test_a_month_without_figures_is_unavailable_not_zero() -> None:
    cost = service.month_cost(service.MonthInputs(year=2026, month=3))

    assert (cost.internal_failure, cost.external_failure, cost.copq) == (None, None, None)
    assert not cost.inputs.reported


def test_recorded_zeros_stay_zero() -> None:
    cost = service.month_cost(service.MonthInputs(year=2026, month=4, outbound_freight=Decimal(0)))

    assert cost.external_failure == Decimal(0)
    assert cost.internal_failure is None
    assert cost.copq == Decimal(0)


def test_percentages_use_sales_and_production_cost_is_per_pound() -> None:
    body = _summary()
    january = body.months[0]

    assert january.copq_pct_of_sales == Decimal("52155.17") / Decimal("10259998")
    assert january.external_pct_of_sales == Decimal("26720") / Decimal("10259998")
    assert january.internal_cost_per_lb == Decimal("25435.17") / Decimal("3887918")
    assert body.months[2].copq_pct_of_sales is None


def test_ratio_without_a_positive_denominator_is_unavailable() -> None:
    cost = service.MonthInputs(
        year=2026, month=5, scrap_produced_lbs=Decimal(1), scrap_loss_per_lb=Decimal(1),
        total_production_lbs=Decimal(0), sales_revenue=Decimal(0),
    )  # fmt: skip
    out = service.summary([cost], year=2026, from_month=5, through_month=5)

    assert out.months[4].internal_cost_per_lb is None
    assert out.months[4].copq_pct_of_sales is None


# Period, Pareto and matrix -------------------------------------------------------


def test_period_defaults_to_the_latest_year_through_its_latest_reported_month() -> None:
    body = _summary()

    assert body.year == 2026 and body.available_years == [2026]
    assert (body.period.from_month, body.period.through_month) == (1, 2)
    assert body.period.reported_months == [1, 2]
    assert body.period.copq == Decimal("75946.92")
    assert body.period.internal_failure == Decimal("46426.92")
    assert body.period.external_failure == Decimal("29520")
    assert body.period.complaint_count == 3
    assert body.period.sales_revenue == Decimal("21766660")
    assert body.period.copq_pct_of_sales == Decimal("75946.92") / Decimal("21766660")
    assert len(body.months) == 12


def test_period_filter_limits_every_total() -> None:
    body = _summary(from_month=2, through_month=2)

    assert body.period.copq == Decimal("23791.75")
    assert body.period.months_in_period == 1
    assert next(e for e in body.elements if e.code == "offspec").value == Decimal("4140.5")


def test_a_period_with_no_figures_is_unavailable() -> None:
    body = _summary(from_month=6, through_month=9)

    assert body.period.copq is None and body.period.months_reported == 0
    assert all(e.value is None for e in body.elements)
    assert body.matrix.poor is None


def test_reversed_period_is_reordered() -> None:
    body = _summary(from_month=2, through_month=1)

    assert (body.period.from_month, body.period.through_month) == (1, 2)


def test_pareto_is_sorted_with_a_cumulative_share() -> None:
    elements = _summary().elements
    values = [e.value for e in elements if e.value is not None]

    assert values == sorted(values, reverse=True)
    assert elements[0].code == "scrap"
    assert elements[0].category == "Scrap"
    reported = [e for e in elements if e.value is not None]
    assert reported[-1].cumulative_share == Decimal(1)
    assert abs(sum((e.share_of_copq or 0 for e in elements), Decimal(0)) - 1) < CLOSE
    assert {e.coq_class for e in elements} == {"internal_failure", "external_failure"}


def test_matrix_never_shows_unrecorded_classes_as_zero() -> None:
    matrix = _summary().matrix
    classes = {c.code: c for c in matrix.classes}

    assert [c.code for c in matrix.classes] == [
        "prevention", "appraisal", "internal_failure", "external_failure",
    ]  # fmt: skip
    assert classes["prevention"].value is None and not classes["prevention"].recorded
    assert classes["appraisal"].value is None and not classes["appraisal"].recorded
    assert classes["internal_failure"].value == Decimal("46426.92")
    assert (matrix.good, matrix.total, matrix.poor_pct) == (None, None, None)
    assert matrix.poor == Decimal("75946.92") == matrix.recorded_total
    assert matrix.unavailable_reason


def test_data_checks_name_the_months_with_blank_lines() -> None:
    checks = _summary().data_checks
    january = [c for c in checks if c.month == 1]

    assert any("Off-spec not reported" in c.message for c in january)
    assert not [c for c in checks if c.month == 2 and c.status == "warning"]
    assert any("pounds" in c.message and c.month is None for c in checks)


def test_no_figures_at_all() -> None:
    body = service.summary([], year=None, from_month=None, through_month=None)

    assert body.year is None and body.months == [] and body.period.copq is None


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


def _stored(path: Path = MAPPING) -> dict[tuple[int, int], CostMonthlyFact]:
    mapping = legacy_import.load_mapping(path)
    return {
        (e.year, e.month): CostMonthlyFact(
            reporting_year=e.year, reporting_month=e.month, **legacy_import.month_values(mapping, e)
        )
        for e in mapping.months
    }


def test_plan_inserts_new_months_and_is_idempotent() -> None:
    mapping = legacy_import.load_mapping(MAPPING)

    first = legacy_import.plan_import({}, mapping)
    again = legacy_import.plan_import(_stored(), mapping)

    assert [(e.year, e.month) for e in first.inserts] == [(2026, 1), (2026, 2)]
    assert (again.inserts, again.differing) == ([], [])
    assert again.unchanged == [(2026, 1), (2026, 2)]


def test_plan_blocks_a_stored_month_that_differs() -> None:
    stored = _stored()
    stored[(2026, 2)].sales_revenue = Decimal("1")

    plan = legacy_import.plan_import(stored, legacy_import.load_mapping(MAPPING))

    assert [(y, m, f) for y, m, f, _, _ in plan.differing] == [(2026, 2, "sales_revenue")]


# API -----------------------------------------------------------------------------


class _Session:
    pass


class _Repository:
    def __init__(self, session: Any) -> None:
        pass

    def facts(self) -> dict[tuple[int, int], Any]:
        return {(m.year, m.month): _Row(m) for m in _months()}


class _Row:
    def __init__(self, month: service.MonthInputs) -> None:
        self.reporting_year, self.reporting_month = month.year, month.month
        self.__dict__.update(
            {k: v for k, v in month.__dict__.items() if k not in ("year", "month")}
        )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(cost_router, "CostRepository", _Repository)

    def make(*permissions: Permission) -> TestClient:
        app = create_app()
        app.dependency_overrides[cost_router.cost_session] = _Session
        app.dependency_overrides[get_user_principal] = lambda: UserPrincipal(
            "tester", authenticated=True, granted=frozenset(permissions)
        )
        return TestClient(app)

    yield make


@pytest.mark.parametrize("path", ["summary", "estimator"])
def test_cost_requires_the_quality_cost_view_permission(api: Any, path: str) -> None:
    url = f"/api/v1/quality/cost/{path}"
    assert api(P.QUALITY_COST_VIEW).get(url).status_code == 200
    assert api(P.QUALITY_VIEW).get(url).status_code == 200
    assert api(P.SAFETY_MANAGE).get(url).status_code == 403
    assert api().get(url).status_code == 403


def test_estimate_requires_the_permission(api: Any) -> None:
    url = "/api/v1/quality/cost/estimate"
    assert api().post(url, json={}).status_code == 403
    assert api(P.QUALITY_COST_VIEW).post(url, json={}).status_code == 200


@pytest.mark.parametrize("path", ["summary", "estimator"])
def test_responses_carry_no_workbook_cell_coordinates(api: Any, path: str) -> None:
    body = api(P.QUALITY_COST_VIEW).get(f"/api/v1/quality/cost/{path}").text

    assert "sourceCell" not in body and "sourceReference" not in body and "!" not in body
    # R0 is the COPQ workbook's revision, not a cell.
    cells = [c for c in re.findall(r"\b[A-Z]{1,3}[0-9]{1,5}\b", body) if c != "R0"]
    assert not cells, cells


def test_summary_json_shape_and_plain_decimals(api: Any) -> None:
    body = api(P.QUALITY_COST_VIEW).get("/api/v1/quality/cost/summary?from=1&through=2").json()

    assert body["period"]["copq"] == "75946.92"
    assert body["months"][0]["elements"]["offspec"] is None
    assert body["months"][2]["copq"] is None
    assert body["matrix"]["good"] is None and body["matrix"]["poorPct"] is None
    assert body["elements"][0]["coqClass"] == "internal_failure"
    decimals = [m["copqPctOfSales"] for m in body["months"]]
    decimals += [e["shareOfCopq"] for e in body["elements"]]
    assert not [d for d in decimals if d is not None and "E" in d.upper()]


@pytest.mark.parametrize("query", ["year=1999", "from=0", "through=13", "year=abc"])
def test_summary_validates_the_period(api: Any, query: str) -> None:
    assert api(P.QUALITY_COST_VIEW).get(f"/api/v1/quality/cost/summary?{query}").status_code == 422


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
