"""Incident & Near Miss dimensions (migration 0007): definitions, import mappings,
saves and the analytics read model.

Section and category definitions come from migrations 0003 and 0007 and the
values from the reviewed import mappings, so no workbook value is retyped here
and the workbook is never read. Uses an in-memory repository (test double only);
PostgreSQL behaviour is covered by test_safety_database.py.
"""

import datetime as dt
import importlib.util
import uuid
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.audit.recorder import AuditChange
from app.safety import analytics, service
from app.safety.legacy_import import (
    LegacyMapping,
    category_ytd,
    load_mapping,
    plan_import,
    total_discrepancies,
)
from app.safety.repository import CategoryDefinition, Cell, SectionDefinition, StoredValues
from app.safety.schemas import CellChange, IncidentAnalyticsResponse
from app.safety.service import UnknownCategoryError

API_ROOT = Path(__file__).resolve().parents[1]
VERSIONS = API_ROOT / "alembic" / "versions"
TEMPLATES = API_ROOT / "import_templates"
TOTALS_2026 = TEMPLATES / "safety_incidents_2026_lcy_ehs.mapping.json"
DIMENSIONS_2026 = TEMPLATES / "safety_incidents_2026_dimensions_lcy_ehs.mapping.json"
TOTALS_2025 = TEMPLATES / "safety_incidents_2025_totals_lcy_ehs.mapping.json"
WORKBOOK_SHA256 = "0B94C09BEDF3C343D3250496780A2D3B66671B55741ABA0391FDE81BE8B51C10"
OCTOBER_8_2026 = dt.datetime(2026, 10, 8, 15, 0, tzinfo=dt.UTC)

DIMENSION_SECTIONS = [
    "incidents_by_area",
    "near_misses_by_area",
    "near_miss_potential",
    "near_miss_cause",
    "lopc_contributing_factor",
    "injury_cause",
    "body_part",
]


def migration(revision: str) -> ModuleType:
    path = next(VERSIONS.glob(f"*-{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0003 = migration("0003")
M0007 = migration("0007")


def seeded_sections() -> list[SectionDefinition]:
    """The incidents set after 0007, in display order (ids are test ids)."""
    sections = []
    for index, (code, name, categories) in enumerate(M0003.INCIDENT_SECTIONS, start=1):
        sections.append(
            SectionDefinition(
                id=index,
                code=code,
                name=name,
                categories=tuple(
                    CategoryDefinition(id=index * 100 + row, code=c, name=n)
                    for row, (c, n) in enumerate(categories, start=1)
                ),
            )
        )
    for index, (code, name, categories) in enumerate(
        M0007.NEW_SECTIONS, start=M0007.FIRST_NEW_SECTION_ORDER
    ):
        if categories is None:
            definitions = tuple(
                CategoryDefinition(
                    id=index * 100 + row,
                    code=area_code,
                    name=area_name,
                    description=area_description,
                    area_kind=kind,
                )
                for row, (area_code, area_name, area_description, kind) in enumerate(
                    M0007.SEED_AREAS, start=1
                )
            )
        else:
            definitions = tuple(
                CategoryDefinition(id=index * 100 + row, code=c, name=n, description=d)
                for row, (c, n, d) in enumerate(categories, start=1)
            )
        sections.append(SectionDefinition(id=index, code=code, name=name, categories=definitions))
    return sections


SECTIONS = seeded_sections()
IDS = {(s.code, c.code): c.id for s in SECTIONS for c in s.categories}
# Safety Performance's legacy set (migration 0006), where 2025 LOPC is read from.
LEGACY_LOPC_ID = 9001
LEGACY_SECTIONS = [
    SectionDefinition(
        id=90,
        code="lopc",
        name="LOPC",
        categories=(CategoryDefinition(id=LEGACY_LOPC_ID, code="lopc", name="LOPC"),),
    )
]
# A test fixture for 2025 legacy LOPC (not workbook values).
LEGACY_LOPC_2025_FIXTURE = {1: 3, 2: 0, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 2, 10: 4}


def stored_from(*mappings: LegacyMapping) -> dict[tuple[int, int, int], int]:
    return {
        (IDS[(s.section, c.category)], mapping.year, month): value
        for mapping in mappings
        for s in mapping.sections
        for c in s.categories
        for month, value in enumerate(c.months, start=1)
        if value is not None
    }


def approved(*, prior: bool = False) -> dict[tuple[int, int, int], int]:
    mappings = [load_mapping(TOTALS_2026), load_mapping(DIMENSIONS_2026)]
    if prior:
        mappings.append(load_mapping(TOTALS_2025))
    return stored_from(*mappings)


class Repository:
    """In-memory test double for reads and saves."""

    def __init__(
        self,
        stored: dict[tuple[int, int, int], int] | None = None,
        legacy: dict[tuple[int, int, int], int] | None = None,
    ) -> None:
        # (category_id, year, month) -> value
        self.stored = dict(stored or {})
        self.stored.update(legacy or {})
        self.pending: dict[tuple[int, int, int], int | None] = {}
        self.audit: list[AuditChange] = []
        self.pending_audit: list[AuditChange] = []

    def sections(self, metric_set: str) -> list[SectionDefinition]:
        if metric_set == "incidents":
            return SECTIONS
        return LEGACY_SECTIONS if metric_set == "performance_legacy" else []

    def values(self, category_ids: Sequence[int], year: int) -> StoredValues:
        return {
            (category, month): value
            for (category, y, month), value in self.stored.items()
            if y == year and category in category_ids
        }

    def years_with_values(self, category_ids: Sequence[int]) -> list[int]:
        return sorted({y for (category, y, _) in self.stored if category in category_ids})

    def lock_year(self, metric_set: str, year: int) -> None:
        pass

    def write(
        self,
        *,
        year: int,
        upserts: dict[Cell, int],
        deletes: Sequence[Cell],
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        for (category, month), value in upserts.items():
            self.pending[(category, year, month)] = value
        for category, month in deletes:
            self.pending[(category, year, month)] = None

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None:
        self.pending_audit.extend(changes)

    def commit(self) -> None:
        for key, value in self.pending.items():
            if value is None:
                self.stored.pop(key, None)
            else:
                self.stored[key] = value
        self.audit.extend(self.pending_audit)
        self.pending, self.pending_audit = {}, []

    def rollback(self) -> None:
        self.pending, self.pending_audit = {}, []


def cells(year: int, **values: dict[int, int]) -> dict[tuple[int, int, int], int]:
    """values: "section__category" -> {month: value}."""
    return {
        (IDS[tuple(key.split("__"))], year, month): value  # type: ignore[index]
        for key, months in values.items()
        for month, value in months.items()
    }


def legacy_lopc(year: int, months: dict[int, int]) -> dict[tuple[int, int, int], int]:
    return {(LEGACY_LOPC_ID, year, month): value for month, value in months.items()}


def load(
    repository: Repository, *, year: int = 2026, through: int | None = 9
) -> IncidentAnalyticsResponse:
    return analytics.load_analytics(
        repository, year=year, through_month=through, now=OCTOBER_8_2026
    )


def totals(rows: Sequence[Any]) -> dict[str, int | None]:
    return {row.code: row.total for row in rows}


# Migration 0007 definitions -----------------------------------------------------------


def test_areas_are_seeded_in_the_approved_order_with_the_owner_kinds() -> None:
    assert [(code, name, kind) for code, name, _, kind in M0007.SEED_AREAS] == [
        ("100", "100", "process_unit"),
        ("200", "200", "process_unit"),
        ("300", "300", "process_unit"),
        ("400", "400", "process_unit"),
        ("500", "500", "process_unit"),
        ("600", "600", "process_unit"),
        ("700", "700", "process_unit"),
        ("800", "800", "process_unit"),
        ("900", "900", "process_unit"),
        ("whse", "WHSE", "support"),
        ("maint", "Maintenance", "support"),
        ("lab", "Lab", "support"),
        ("mundy", "MUNDY", "organization"),
        ("admin", "Admin", "support"),
        ("third_party", "3rd Party", "organization"),
    ]
    described = {code for code, _, description, _ in M0007.SEED_AREAS if description}
    assert described == {"100", "200", "300", "400", "500", "600", "700", "800", "900"}


def test_new_sections_follow_the_six_existing_sections() -> None:
    assert [s.code for s in SECTIONS][6:] == DIMENSION_SECTIONS
    assert len(M0003.INCIDENT_SECTIONS) + 1 == M0007.FIRST_NEW_SECTION_ORDER
    for code in ("incidents_by_area", "near_misses_by_area"):
        section = next(s for s in SECTIONS if s.code == code)
        assert [c.code for c in section.categories] == [a[0] for a in M0007.SEED_AREAS]


def test_dimension_taxonomies_are_complete() -> None:
    by_code = {s.code: [c.code for c in s.categories] for s in SECTIONS}
    assert len(by_code["near_miss_cause"]) == 11
    assert by_code["near_miss_potential"] == [
        "sif",
        "lost_time_injury",
        "exposure",
        "fire",
        "property_damage",
        "environmental_release",
        "business_interruption",
    ]
    assert by_code["lopc_contributing_factor"] == ["mechanical_integrity", "human_error", "other"]
    assert len(by_code["injury_cause"]) == 14
    assert "contact_by" in by_code["injury_cause"]
    assert len(by_code["body_part"]) == 27
    assert "leg" in by_code["body_part"]
    causes = next(s for s in SECTIONS if s.code == "near_miss_cause")
    assert all(c.description for c in causes.categories)


def test_no_unapproved_dimension_is_seeded() -> None:
    codes = {s.code for s in SECTIONS}
    for excluded in ("behavior", "process_safety", "psm", "material", "electrical", "lopc_failure"):
        assert not any(excluded in code for code in codes), excluded


# Import mappings -----------------------------------------------------------------------


def test_dimensions_mapping_targets_only_the_new_sections_and_known_categories() -> None:
    mapping = load_mapping(DIMENSIONS_2026)

    assert (mapping.metric_set, mapping.year) == ("incidents", 2026)
    assert WORKBOOK_SHA256 in mapping.source
    assert [s.section for s in mapping.sections] == [
        "incidents_by_area",
        "near_misses_by_area",
        "lopc_contributing_factor",
        "near_miss_potential",
        "near_miss_cause",
        "injury_cause",
        "body_part",
    ]
    for section in mapping.sections:
        for category in section.categories:
            assert (section.section, category.category) in IDS
            # Strict blanks: nothing after September, and no zero was invented.
            assert category.months[9:] == [None, None, None]
            assert 0 not in category.months
    assert total_discrepancies(mapping) == []


def area_monthly_sums(section: str) -> list[int | None]:
    mapping = load_mapping(DIMENSIONS_2026)
    rows = next(s for s in mapping.sections if s.section == section).categories
    return [service.total(row.months[m] for row in rows) for m in range(9)]


def approved_monthly(category: str) -> list[int | None]:
    mapping = load_mapping(TOTALS_2026)
    section = "lopc" if category == "lopc" else "incident_near_miss_totals"
    rows = next(s for s in mapping.sections if s.section == section).categories
    return next(row for row in rows if row.category == category).months[:9]


def test_area_grids_reconcile_with_the_approved_totals_every_month() -> None:
    assert area_monthly_sums("incidents_by_area") == approved_monthly("incident")
    assert sum(approved_monthly("incident")) == 41  # type: ignore[arg-type]
    # May is 3 (WHSE 2 + 3rd Party 1), not the Dash!G41 value of 2.
    assert area_monthly_sums("incidents_by_area")[4] == 3
    assert area_monthly_sums("near_misses_by_area") == approved_monthly("near_miss")
    assert area_monthly_sums("lopc_contributing_factor") == approved_monthly("lopc")


def test_tag_mappings_keep_the_monthly_cells_not_the_stale_summaries() -> None:
    ytd = category_ytd(load_mapping(DIMENSIONS_2026))

    assert ytd[("near_miss_potential", "environmental_release")] == 5
    assert ytd[("near_miss_cause", "equipment_maintenance")] == 12
    assert ytd[("injury_cause", "contact_by")] == 1
    assert ytd[("body_part", "leg")] == 1
    injury = sum(v for (s, _), v in ytd.items() if s == "injury_cause" and v is not None)
    body = sum(v for (s, _), v in ytd.items() if s == "body_part" and v is not None)
    assert injury == body == 6


def test_2025_mapping_is_the_incident_total_only_with_a_typed_february_zero() -> None:
    mapping = load_mapping(TOTALS_2025)

    assert (mapping.metric_set, mapping.year) == ("incidents", 2025)
    assert WORKBOOK_SHA256 in mapping.source
    assert [(s.section, [c.category for c in s.categories]) for s in mapping.sections] == [
        ("incident_near_miss_totals", ["incident"])
    ]
    months = mapping.sections[0].categories[0].months
    assert months == [5, 0, 4, 5, 2, 4, 6, 6, 4, 2, 1, 2]
    assert sum(months) == 41  # type: ignore[arg-type]
    assert total_discrepancies(mapping) == []


def test_import_plans_insert_reported_cells_only_and_are_idempotent() -> None:
    repository = Repository(stored_from(load_mapping(TOTALS_2026)))
    for path, expected in ((DIMENSIONS_2026, 122), (TOTALS_2025, 12)):
        mapping = load_mapping(path)
        plan = plan_import(repository, mapping)
        assert (len(plan.changes), plan.unknown, plan.differing) == (expected, [], [])
        assert all(change.value is not None for change in plan.changes)
        service.save_changes(
            repository,
            metric_set=mapping.metric_set,
            year=mapping.year,
            changes=plan.changes,
            actor_id="legacy-import",
            now=OCTOBER_8_2026,
        )
        again = plan_import(repository, mapping)
        assert (again.changes, again.unchanged) == ([], expected)
    # The 2025 February zero is stored as a zero, not skipped.
    assert repository.stored[(IDS[("incident_near_miss_totals", "incident")], 2025, 2)] == 0


def test_import_plan_reports_a_category_missing_before_0007() -> None:
    class Before0007(Repository):
        def sections(self, metric_set: str) -> list[SectionDefinition]:
            return SECTIONS[:6] if metric_set == "incidents" else []

    plan = plan_import(Before0007(), load_mapping(DIMENSIONS_2026))

    assert plan.changes == []
    assert ("incidents_by_area", "mundy") in plan.unknown


# Saves ---------------------------------------------------------------------------------


def save(repository: Repository, *changes: CellChange) -> service.SaveOutcome:
    return service.save_changes(
        repository,
        metric_set="incidents",
        year=2026,
        changes=list(changes),
        actor_id="tester",
        now=OCTOBER_8_2026,
    )


def change(key: tuple[str, str], month: int, value: int | None, previous: int | None) -> CellChange:
    return CellChange(category_id=IDS[key], month=month, value=value, previous_value=previous)


def test_area_and_tag_cells_save_zero_clear_and_audit() -> None:
    mundy = ("incidents_by_area", "mundy")
    leg = ("body_part", "leg")
    repository = Repository(cells(2026, incidents_by_area__mundy={2: 2}))

    save(repository, change(mundy, 1, 0, None), change(mundy, 2, None, 2), change(leg, 9, 1, None))

    assert repository.stored == {(IDS[mundy], 2026, 1): 0, (IDS[leg], 2026, 9): 1}
    assert {c.entity_key: c.action for c in repository.audit} == {
        "incidents/incidents_by_area/mundy/2026-01": "create",
        "incidents/incidents_by_area/mundy/2026-02": "delete",
        "incidents/body_part/leg/2026-09": "create",
    }


def test_a_category_outside_the_incidents_set_is_refused() -> None:
    repository = Repository()
    unknown = CellChange(category_id=LEGACY_LOPC_ID, month=1, value=1, previous_value=None)

    with pytest.raises(UnknownCategoryError):
        save(repository, unknown)
    assert repository.stored == {}


@pytest.mark.parametrize("value", [-1, 1.5, "2"])
def test_area_values_must_be_whole_non_negative_numbers(value: Any) -> None:
    with pytest.raises(ValueError):
        CellChange.model_validate(
            {"categoryId": IDS[("incidents_by_area", "100")], "month": 1, "value": value}
        )


# Read model ----------------------------------------------------------------------------


def test_area_breakdowns_list_reported_areas_by_total_then_display_order() -> None:
    result = load(Repository(approved()))

    incidents = [(row.code, row.total) for row in result.incidents_by_area]
    assert incidents == [
        ("mundy", 14),
        ("third_party", 6),
        ("200", 4),
        ("400", 4),
        ("600", 3),
        ("100", 2),
        ("300", 2),
        ("500", 2),
        ("700", 2),
        ("whse", 2),
    ]
    assert sum(total for _, total in incidents) == 41  # type: ignore[misc]
    assert sum(row.total or 0 for row in result.near_misses_by_area) == 31
    # The heatmaps keep every area in display order, unreported ones included.
    assert [row.code for row in result.incident_area_monthly] == [a[0] for a in M0007.SEED_AREAS]
    admin = next(row for row in result.incident_area_monthly if row.code == "admin")
    assert (admin.values, admin.total, admin.months_reported) == ([None] * 9, None, 0)
    assert result.incident_area_monthly[0].area_kind == "process_unit"


def test_area_reconciliation_of_the_approved_values() -> None:
    result = load(Repository(approved()))

    incidents = result.area_reconciliation.incidents
    assert {m.status for m in incidents} == {"reconciled"}
    assert incidents[4].dimension_total == incidents[4].authoritative_total == 3
    near_misses = {m.month: m.status for m in result.area_reconciliation.near_misses}
    # February and March have no Near Miss total and no area values.
    assert near_misses == {
        1: "reconciled",
        2: "no_authoritative_total",
        3: "no_authoritative_total",
        **{month: "reconciled" for month in range(4, 10)},
    }


def test_a_reconciled_month_does_not_turn_blank_areas_into_zero() -> None:
    result = load(Repository(approved()))

    may = {row.code: row.values[4] for row in result.incident_area_monthly}
    assert (may["whse"], may["third_party"]) == (2, 1)
    assert may["100"] is None and may["mundy"] is None


def test_reconciliation_statuses() -> None:
    repository = Repository(
        cells(
            2026,
            incident_near_miss_totals__incident={1: 2, 2: 2, 3: 2, 4: 0},
            incidents_by_area__100={1: 1, 2: 2, 3: 3},
            incidents_by_area__200={5: 1},
        )
    )

    result = load(repository, through=5)

    assert [
        (m.status, m.dimension_total, m.authoritative_total, m.difference)
        for m in result.area_reconciliation.incidents
    ] == [
        ("below_total", 1, 2, -1),
        ("reconciled", 2, 2, 0),
        ("above_total", 3, 2, 1),
        ("no_dimension_data", None, 0, None),
        ("no_authoritative_total", 1, None, None),
    ]
    # The authoritative Incident total is never changed by the areas.
    assert result.incidents.values == [2, 2, 2, 0, None]


def test_explicit_zero_area_is_reported_and_blank_is_not() -> None:
    repository = Repository(cells(2026, incidents_by_area__lab={1: 0}))

    result = load(repository, through=1)

    assert [(row.code, row.total) for row in result.incidents_by_area] == [("lab", 0)]
    lab = next(row for row in result.incident_area_monthly if row.code == "lab")
    assert (lab.values, lab.months_reported) == ([0], 1)
    assert result.area_reconciliation.incidents[0].status == "no_authoritative_total"


def test_months_after_through_do_not_contribute() -> None:
    result = load(Repository(approved()), through=4)

    assert totals(result.incidents_by_area)["mundy"] == 9
    assert result.near_miss_cause.monthly_totals[:1] == [7]
    assert len(result.injury_cause.monthly_totals) == 4


def test_lopc_factors_cumulate_and_reconcile_with_lopc() -> None:
    result = load(Repository(approved()))
    factors = result.lopc_contributing_factors

    assert totals(factors.breakdown.categories) == {
        "mechanical_integrity": 9,
        "human_error": 4,
        "other": 1,
    }
    assert factors.cumulative_total == [1, 3, 5, 6, 6, 8, 11, 13, 14]
    other = next(row for row in factors.cumulative if row.code == "other")
    assert other.values == [None] * 8 + [1]
    statuses = {m.month: m.status for m in result.lopc_factor_reconciliation}
    assert statuses[5] == "no_authoritative_total"
    assert {s for month, s in statuses.items() if month != 5} == {"reconciled"}


def test_lopc_factor_mismatch_is_a_warning_not_a_change() -> None:
    repository = Repository(
        cells(
            2026,
            lopc__lopc={1: 2},
            lopc_contributing_factor__mechanical_integrity={1: 1},
            lopc_contributing_factor__human_error={1: 2},
        )
    )

    result = load(repository, through=1)

    assert result.lopc_factor_reconciliation[0].status == "above_total"
    assert result.lopc.total == 2
    assert next(k for k in result.kpis if k.key == "lopc").value == 2


def test_cumulative_carries_through_blanks_and_starts_null() -> None:
    assert analytics.cumulative([None, 2, None, 0, 3]) == [None, 2, 2, 2, 5]
    assert analytics.cumulative([]) == []


def test_tags_may_exceed_the_event_counts() -> None:
    result = load(Repository(approved()))

    potential = result.near_miss_potential
    cause = result.near_miss_cause
    assert potential.is_tag and cause.is_tag
    assert potential.total == 38
    assert cause.total == 52
    assert result.near_misses.total == 31
    assert totals(potential.categories)["environmental_release"] == 5
    assert totals(cause.categories)["equipment_maintenance"] == 12
    assert [row.code for row in cause.categories][:2] == [
        "human_performance",
        "equipment_maintenance",
    ]
    areas = {row.code: row for row in result.incident_area_monthly}
    assert (areas["100"].description, areas["mundy"].description) == ("Ingredient Prep", None)
    assert all(row.description for row in cause.categories)


def test_injury_dimensions_reconcile_with_first_aid_plus_recordable() -> None:
    result = load(Repository(approved()))
    injury = result.injury_reconciliation

    assert result.injury_cause.total == result.body_part.total == 6
    assert result.injury_cause.is_tag and result.body_part.is_tag
    for month in injury.injury_cause + injury.body_part:
        if month.dimension_total is not None:
            assert month.status == "reconciled"
            assert month.authoritative_total == injury.injuries[month.month - 1]


def test_body_parts_above_the_injury_count_are_a_difference_not_invalid() -> None:
    repository = Repository(
        cells(
            2026,
            incident_classification__first_aid={1: 1},
            body_part__hand={1: 1},
            body_part__fingers={1: 1},
        )
    )

    result = load(repository, through=1)

    month = result.injury_reconciliation.body_part[0]
    assert (month.status, month.difference) == ("above_total", 1)
    assert result.injury_reconciliation.injuries == [1]


def test_prior_year_incidents_and_lopc() -> None:
    repository = Repository(
        approved(prior=True),
        legacy=legacy_lopc(2025, LEGACY_LOPC_2025_FIXTURE),
    )

    result = load(repository)

    assert result.prior_year == 2025
    incidents = result.incidents_prior_year_monthly
    assert incidents.values == [5, 0, 4, 5, 2, 4, 6, 6, 4]
    assert incidents.values[1] == 0
    assert result.incidents_prior_year_available is True
    kpi = next(k for k in result.kpis if k.key == "incidents")
    assert kpi.prior_year is not None
    assert (kpi.prior_year.year, kpi.prior_year.value, kpi.prior_year.delta) == (2025, 36, 5)
    assert result.lopc_prior_year_monthly.values == [3, 0, 1, 1, 1, 1, 1, 1, 2]
    assert result.lopc_prior_year_monthly.total == 11
    lopc = next(k for k in result.kpis if k.key == "lopc")
    assert lopc.prior_year is not None and lopc.prior_year.delta == 3
    # Only Incidents and LOPC carry a prior year.
    assert all(k.prior_year is None for k in result.kpis if k.key not in {"incidents", "lopc"})


def test_prior_year_lopc_is_read_from_the_legacy_set_before_2026() -> None:
    repository = Repository(cells(2025, lopc__lopc={1: 50}), legacy=legacy_lopc(2025, {1: 3}))

    result = load(repository, through=1)

    assert result.lopc_prior_year_monthly.values == [3]


def test_an_unavailable_prior_year_is_null_not_zero() -> None:
    result = load(Repository(approved()))

    assert result.incidents_prior_year_available is False
    assert result.incidents_prior_year_monthly.values == [None] * 9
    assert result.lopc_prior_year_available is False
    assert all(k.prior_year is None for k in result.kpis)


def test_prior_year_follows_the_through_month() -> None:
    repository = Repository(approved(prior=True))

    result = load(repository, through=2)

    assert result.incidents_prior_year_monthly.values == [5, 0]
    kpi = next(k for k in result.kpis if k.key == "incidents")
    assert kpi.prior_year is not None and kpi.prior_year.value == 5


def test_behavior_has_no_source_and_returns_nothing() -> None:
    result = load(Repository(approved()))

    assert (result.behavior_available, result.behavior_data) == (False, None)


def test_a_future_year_has_empty_breakdowns() -> None:
    result = analytics.load_analytics(
        Repository(approved()),
        year=2027,
        through_month=None,
        now=dt.datetime(2027, 1, 1, 5, 59, tzinfo=dt.UTC),
    )

    assert result.through_month is None
    assert result.incidents_by_area == []
    assert all(row.values == [] for row in result.incident_area_monthly)
    assert result.area_reconciliation.incidents == []
    assert result.lopc_contributing_factors.cumulative_total == []


def test_sets_without_0007_sections_still_load() -> None:
    class Before0007(Repository):
        def sections(self, metric_set: str) -> list[SectionDefinition]:
            return SECTIONS[:6] if metric_set == "incidents" else []

    result = load(Before0007(approved()))

    assert result.incidents.total == 41
    assert result.incidents_by_area == [] and result.incident_area_monthly == []
    assert result.near_miss_cause.categories == []
