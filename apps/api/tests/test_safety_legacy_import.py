import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_safety import InMemoryRepository

from app.safety import legacy_import
from app.safety.legacy_import import (
    LegacyMapping,
    TotalDiscrepancy,
    category_ytd,
    load_mapping,
    plan_import,
    total_discrepancies,
)

API_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = API_ROOT / "import_templates" / "safety_incidents.template.json"
MIGRATION_0003 = next((API_ROOT / "alembic" / "versions").glob("*-0003_*.py"))
OBSERVATIONS_TEMPLATE = API_ROOT / "import_templates" / "safety_observations_legacy.template.json"
MIGRATION_0004 = next((API_ROOT / "alembic" / "versions").glob("*-0004_*.py"))


def months(values: dict[int, int]) -> list[int | None]:
    return [values.get(month) for month in range(1, 13)]


def mapping(**overrides: Any) -> LegacyMapping:
    data: dict[str, Any] = {
        "source": "test workbook",
        "metricSet": "incidents",
        "year": 2026,
        "sections": [
            {
                "section": "incident_classification",
                "categories": [
                    {"category": "first_aid", "months": months({1: 2})},
                    {"category": "recordable_injury", "months": months({1: 1})},
                ],
            },
            {
                "section": "incident_near_miss_totals",
                "categories": [
                    {"category": "near_miss", "months": months({2: 0})},
                    {"category": "incident", "months": months({1: 2})},
                ],
            },
        ],
    }
    data.update(overrides)
    return LegacyMapping.model_validate(data)


def test_ytd_is_per_category_and_null_when_unreported() -> None:
    ytd = category_ytd(mapping())

    assert ytd[("incident_near_miss_totals", "incident")] == 2
    assert ytd[("incident_near_miss_totals", "near_miss")] == 0
    assert ytd[("incident_classification", "first_aid")] == 2


def test_stated_totals_are_checked_against_the_explicit_metric_not_classifications() -> None:
    # Classifications sum to 3 here; the explicit Incident metric is 2.
    m = mapping(
        expectedYtd=[
            {
                "section": "incident_near_miss_totals",
                "category": "incident",
                "value": 2,
                "statedIn": "Total EHS Incidents",
            },
            {"section": "pit", "category": "pit", "value": 1, "statedIn": "PIT total"},
        ]
    )

    assert total_discrepancies(m) == [
        TotalDiscrepancy(section="pit", category="pit", expected=1, calculated=None)
    ]


def test_stated_totals_that_disagree_are_reported_not_adjusted() -> None:
    m = mapping(
        expectedYtd=[
            {
                "section": "incident_near_miss_totals",
                "category": "incident",
                "value": 3,
                "statedIn": "Total EHS Incidents",
            }
        ]
    )

    assert total_discrepancies(m) == [
        TotalDiscrepancy(
            section="incident_near_miss_totals", category="incident", expected=3, calculated=2
        )
    ]


def section(*categories: dict[str, Any], code: str = "pit") -> dict[str, Any]:
    return {"section": code, "categories": list(categories)}


@pytest.mark.parametrize(
    "sections",
    [
        [section({"category": "pit", "months": [-1] + [None] * 11})],
        [section({"category": "pit", "months": [1.5] + [None] * 11})],
        [section({"category": "pit", "months": ["1"] + [None] * 11})],
        [section({"category": "pit", "months": [None] * 11})],
        [section({"category": "pit", "months": [None] * 13})],
        [section({"category": "PIT", "months": [None] * 12})],
        [section({"category": "pit", "months": [None] * 12, "extra": 1})],
        [section()],
        [
            section(
                {"category": "pit", "months": [None] * 12},
                {"category": "pit", "months": [None] * 12},
            )
        ],
        [
            section({"category": "pit", "months": [None] * 12}),
            section({"category": "pit", "months": [None] * 12}),
        ],
        [],
    ],
)
def test_invalid_mappings_are_rejected(sections: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        mapping(sections=sections)


def test_plan_inserts_new_cells_and_flags_differences() -> None:
    # first_aid Jan stored 2 (same), recordable Jan stored 5 (file 1).
    repository = InMemoryRepository({(11, 2026, 1): 2, (12, 2026, 1): 5})

    plan = plan_import(repository, mapping())

    assert [(c.category_id, c.month, c.value, c.previous_value) for c in plan.changes] == [
        (21, 2, 0, None),
        (22, 1, 2, None),
    ]
    assert plan.unchanged == 1
    assert plan.unreported == 4 * 12 - 4
    assert plan.differing == [("incident_classification", "recordable_injury", 1, 5, 1)]


def test_unreported_in_file_never_clears_a_stored_value() -> None:
    repository = InMemoryRepository({(22, 2026, 5): 4})

    plan = plan_import(repository, mapping())

    assert ("incident_near_miss_totals", "incident", 5, 4, None) in plan.differing
    assert all(change.value is not None for change in plan.changes)


def test_plan_reports_unknown_categories() -> None:
    m = mapping(sections=[section({"category": "pit", "months": months({1: 1})})])

    plan = plan_import(InMemoryRepository(), m)

    assert plan.unknown == [("pit", "pit")]
    assert plan.changes == []


def write(tmp_path: Path, m: LegacyMapping) -> Path:
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(m.model_dump(by_alias=True)), encoding="utf-8")
    return path


def test_check_command_fails_on_discrepancies(tmp_path: Path) -> None:
    m = mapping(
        expectedYtd=[
            {
                "section": "incident_near_miss_totals",
                "category": "incident",
                "value": 3,
                "statedIn": "x",
            }
        ]
    )

    assert legacy_import.run("check", write(tmp_path, m)) == 1


def test_check_command_accepts_a_consistent_file(tmp_path: Path) -> None:
    m = mapping(
        expectedYtd=[
            {
                "section": "incident_near_miss_totals",
                "category": "incident",
                "value": 2,
                "statedIn": "x",
            }
        ]
    )

    assert legacy_import.run("check", write(tmp_path, m)) == 0


def test_check_command_rejects_malformed_files(tmp_path: Path) -> None:
    path = tmp_path / "mapping.json"
    path.write_text("{not json", encoding="utf-8")

    assert legacy_import.run("check", path) == 2


# Template --------------------------------------------------------------------------


def seeded_sections() -> list[tuple[str, list[str]]]:
    spec = importlib.util.spec_from_file_location("migration_0003", MIGRATION_0003)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [(code, [c for c, _ in categories]) for code, _, categories in module.INCIDENT_SECTIONS]


def test_template_covers_every_seeded_section_and_category() -> None:
    template = load_mapping(TEMPLATE)

    listed = [(s.section, [c.category for c in s.categories]) for s in template.sections]
    assert sorted((code, sorted(cats)) for code, cats in listed) == sorted(
        (code, sorted(cats)) for code, cats in seeded_sections()
    )
    assert [s.section for s in template.sections][:2] == [
        "incident_near_miss_totals",
        "incident_classification",
    ]


def test_template_contains_no_values() -> None:
    template = load_mapping(TEMPLATE)

    assert all(cell.value is None for cell in legacy_import.cells(template))
    assert template.expected_ytd == []


def test_template_passes_check(tmp_path: Path) -> None:
    assert legacy_import.run("check", TEMPLATE) == 0


def load_migration_0004() -> Any:
    spec = importlib.util.spec_from_file_location("migration_0004", MIGRATION_0004)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_observations_template_covers_every_seeded_legacy_section() -> None:
    migration = load_migration_0004()
    template = load_mapping(OBSERVATIONS_TEMPLATE)

    assert template.metric_set == migration.LEGACY_METRIC_SET == "observations_legacy"
    listed = [(s.section, [c.category for c in s.categories]) for s in template.sections]
    assert listed == [
        (code, [c for c, _ in categories]) for code, _, categories in migration.LEGACY_SECTIONS
    ]


def test_observations_template_keeps_fire_and_fire_system_apart() -> None:
    template = load_mapping(OBSERVATIONS_TEMPLATE)
    by_section = {s.section: {c.category for c in s.categories} for s in template.sections}

    assert "fire" in by_section["safe_by_category"]
    assert "fire_system" not in by_section["safe_by_category"]
    assert "fire_system" in by_section["unsafe_by_category"]
    assert "fire" not in by_section["unsafe_by_category"]


def test_observations_template_contains_no_values_and_passes_check() -> None:
    template = load_mapping(OBSERVATIONS_TEMPLATE)

    assert all(cell.value is None for cell in legacy_import.cells(template))
    assert template.expected_ytd == []
    assert legacy_import.run("check", OBSERVATIONS_TEMPLATE) == 0
