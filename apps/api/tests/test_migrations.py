"""Migration placement checks using Alembic offline SQL. No database required."""

import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture
def upgrade_sql(monkeypatch: pytest.MonkeyPatch) -> str:
    # Offline mode needs a dialect only; nothing connects to this placeholder URL.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://placeholder@localhost/placeholder")
    get_settings.cache_clear()
    buffer = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=buffer)
    config.attributes["configure_logger"] = False
    try:
        command.upgrade(config, "head", sql=True)
    finally:
        get_settings.cache_clear()
    return buffer.getvalue()


def test_version_table_is_core_alembic_version(upgrade_sql: str) -> None:
    assert "CREATE TABLE core.alembic_version" in upgrade_sql
    assert "INSERT INTO core.alembic_version" in upgrade_sql


def test_finishing_measurements_is_created_in_quality(upgrade_sql: str) -> None:
    assert "CREATE TABLE quality.finishing_measurements" in upgrade_sql


def test_ingestion_batches_is_created_in_core(upgrade_sql: str) -> None:
    assert "CREATE TABLE core.ingestion_batches" in upgrade_sql
    assert "REFERENCES core.ingestion_batches" in upgrade_sql


def test_no_objects_are_created_in_public(upgrade_sql: str) -> None:
    created = re.findall(r"CREATE (?:TABLE|INDEX \S+ ON) (\S+)", upgrade_sql)
    assert created
    assert all(name.split(".")[0] in {"core", "quality", "safety"} for name in created), created
    assert "public." not in upgrade_sql


def test_migrations_never_create_the_core_schema(upgrade_sql: str) -> None:
    assert "CREATE SCHEMA core" not in upgrade_sql


def test_audit_events_is_created_in_core(upgrade_sql: str) -> None:
    assert "CREATE TABLE core.audit_events" in upgrade_sql


def test_safety_tables_are_created_in_safety(upgrade_sql: str) -> None:
    for table in ("metric_sections", "metric_categories", "monthly_metric_values"):
        assert f"CREATE TABLE safety.{table}" in upgrade_sql
    assert "uq_monthly_metric_values_category_year_month" in upgrade_sql
    assert "value >= 0" in upgrade_sql


def test_safety_seeds_definitions_but_no_values(upgrade_sql: str) -> None:
    assert "INSERT INTO safety.metric_sections" in upgrade_sql
    assert "INSERT INTO safety.metric_categories" in upgrade_sql
    assert "'Lost Time Injury'" in upgrade_sql
    assert "INSERT INTO safety.monthly_metric_values" not in upgrade_sql


def test_observation_tables_are_created_in_safety(upgrade_sql: str) -> None:
    assert "CREATE TABLE safety.observation_categories" in upgrade_sql
    assert "CREATE TABLE safety.observations" in upgrade_sql
    assert "REFERENCES safety.observation_categories" in upgrade_sql
    assert "outcome IN ('safe', 'unsafe')" in upgrade_sql
    assert "kind IN ('act', 'condition')" in upgrade_sql


def test_observation_categories_are_seeded_but_no_observations(upgrade_sql: str) -> None:
    assert "INSERT INTO safety.observation_categories" in upgrade_sql
    for name in ("'Housekeeping'", "'Fire'", "'Fire System'", "'Tools & Equipment'"):
        assert name in upgrade_sql
    assert "Housekeepng" not in upgrade_sql
    assert "INSERT INTO safety.observations " not in upgrade_sql
    assert "'observations_legacy'" in upgrade_sql


def test_contact_tables_are_created_in_safety(upgrade_sql: str) -> None:
    assert "CREATE TABLE safety.contact_supervisors" in upgrade_sql
    assert "CREATE TABLE safety.supervisor_safety_contacts" in upgrade_sql
    assert "REFERENCES safety.contact_supervisors (id) ON DELETE RESTRICT" in upgrade_sql
    assert (
        "CREATE UNIQUE INDEX uq_contact_supervisors_display_name "
        "ON safety.contact_supervisors (lower(display_name))"
    ) in upgrade_sql


def test_performance_tables_are_created_in_safety(upgrade_sql: str) -> None:
    assert "CREATE TABLE safety.performance_hours" in upgrade_sql
    assert "CREATE TABLE safety.performance_annual_legacy" in upgrade_sql
    assert "uq_performance_hours_year_month UNIQUE (reporting_year, reporting_month)" in upgrade_sql
    assert "total_hours NUMERIC(10, 2) NOT NULL" in upgrade_sql
    assert "month_closed BOOLEAN DEFAULT false NOT NULL" in upgrade_sql
    assert "hourly_hours + salary_hours = total_hours" in upgrade_sql
    assert "contractor" not in _segment(upgrade_sql, "0005 -> 0006", "0006 -> 0007")


def _segment(sql: str, start: str, end: str | None = None) -> str:
    segment = sql.split(f"Running upgrade {start}", 1)[1]
    return segment.split(f"Running upgrade {end}", 1)[0] if end else segment


def test_performance_migration_seeds_legacy_definitions_only(upgrade_sql: str) -> None:
    performance_sql = _segment(upgrade_sql, "0005 -> 0006", "0006 -> 0007")
    assert "'performance_legacy'" in performance_sql
    assert "INSERT INTO safety.metric_sections" in performance_sql
    assert "INSERT INTO safety.metric_categories" in performance_sql
    assert "INSERT INTO safety.monthly_metric_values" not in performance_sql
    assert "INSERT INTO safety.performance_hours" not in performance_sql
    assert "INSERT INTO safety.performance_annual_legacy" not in performance_sql
    assert "target" not in performance_sql.lower()
    assert "DROP" not in performance_sql
    assert "ALTER TABLE" not in performance_sql


def test_contacts_migration_seeds_no_names_contacts_or_targets(upgrade_sql: str) -> None:
    contacts_sql = upgrade_sql.split("Running upgrade 0004 -> 0005", 1)[1]
    contacts_sql = contacts_sql.split("Running upgrade 0005 -> 0006", 1)[0]
    assert "INSERT" not in contacts_sql
    assert "target" not in contacts_sql.lower()
    assert "DROP" not in contacts_sql
    assert "ALTER TABLE" not in contacts_sql


def test_incident_dimensions_migration_creates_areas_and_definitions_only(upgrade_sql: str) -> None:
    dimensions_sql = _segment(upgrade_sql, "0006 -> 0007", "0007 -> 0008")
    assert "CREATE TABLE safety.areas" in dimensions_sql
    assert "area_kind IN ('process_unit', 'support', 'organization')" in dimensions_sql
    assert "ADD COLUMN area_id INTEGER" in dimensions_sql
    assert "REFERENCES safety.areas (id) ON DELETE RESTRICT" in dimensions_sql
    assert "CREATE UNIQUE INDEX uq_metric_categories_section_area" in dimensions_sql
    assert "WHERE area_id IS NOT NULL" in dimensions_sql
    assert "CREATE TRIGGER trg_metric_categories_area_rule" in dimensions_sql
    assert "CREATE TRIGGER trg_metric_sections_area_rule" in dimensions_sql
    assert "INSERT INTO safety.areas" in dimensions_sql
    for section in (
        "incidents_by_area",
        "near_misses_by_area",
        "near_miss_potential",
        "near_miss_cause",
        "lopc_contributing_factor",
        "injury_cause",
        "body_part",
    ):
        assert f"'{section}'" in dimensions_sql
    assert "INSERT INTO safety.monthly_metric_values" not in dimensions_sql
    assert "UPDATE safety.monthly_metric_values" not in dimensions_sql
    assert "DROP" not in dimensions_sql
    for excluded in ("behavior", "process_safety", "psm", "electrical", "material"):
        assert f"'{excluded}" not in dimensions_sql.lower()


def test_behavior_migration_stores_annual_counts_without_months(upgrade_sql: str) -> None:
    behavior_sql = _segment(upgrade_sql, "0007 -> 0008", "0008 -> 0009")
    assert "CREATE TABLE safety.behavior_categories" in behavior_sql
    assert "CREATE TABLE safety.annual_behavior_counts" in behavior_sql
    counts_table = behavior_sql.split("CREATE TABLE safety.annual_behavior_counts", 1)[1]
    counts_table = counts_table.split(";", 1)[0]
    assert "reporting_year SMALLINT NOT NULL" in counts_table
    assert "month" not in counts_table.lower()
    assert "UNIQUE (category_id, reporting_year)" in counts_table
    assert "REFERENCES safety.behavior_categories (id) ON DELETE RESTRICT" in counts_table
    assert "value >= 0" in counts_table
    assert behavior_sql.count("'pre_post_job_inspection'") == 1
    assert "'confined_space'" in behavior_sql
    # Definitions only: no counts, and nothing existing is changed.
    assert "INSERT INTO safety.annual_behavior_counts" not in behavior_sql
    assert "monthly_metric_values" not in behavior_sql
    assert "metric_sections" not in behavior_sql
    assert "DROP" not in behavior_sql
    assert "ALTER TABLE" not in behavior_sql


def test_records_migration_creates_records_and_trir_history_only(upgrade_sql: str) -> None:
    sql = _segment(upgrade_sql, "0008 -> 0009", "0009 -> 0010")
    assert "CREATE TABLE safety.incident_records" in sql
    assert "CREATE TABLE safety.trir_annual_facts" in sql
    records = sql.split("CREATE TABLE safety.incident_records", 1)[1].split(";", 1)[0]
    # The reporting month is derived from the date, never stored.
    assert "incident_date DATE NOT NULL" in records
    assert "month" not in records.lower()
    assert "REFERENCES safety.areas (id) ON DELETE RESTRICT" in records
    assert "REFERENCES safety.metric_categories (id) ON DELETE RESTRICT" in records
    assert "REFERENCES safety.incident_records (id) ON DELETE RESTRICT" in records
    assert (
        "CREATE UNIQUE INDEX uq_incident_records_incident_number "
        "ON safety.incident_records (incident_number) WHERE incident_number IS NOT NULL"
    ) in sql
    assert "CREATE TRIGGER trg_incident_records_classification_rule" in sql
    facts = sql.split("CREATE TABLE safety.trir_annual_facts", 1)[1].split(";", 1)[0]
    assert "month" not in facts.lower()
    # Schema only: nothing seeded, nothing existing altered or dropped.
    assert "INSERT" not in sql.replace("INSERT INTO core.alembic_version", "").replace(
        "BEFORE INSERT OR UPDATE", ""
    ).replace("UPDATE core.alembic_version", "")
    assert "ALTER TABLE" not in sql
    assert "DROP" not in sql


def test_cost_migration_creates_monthly_inputs_only(upgrade_sql: str) -> None:
    sql = _segment(upgrade_sql, "0009 -> 0010", "0010 -> 0011")
    assert "CREATE TABLE quality.cost_monthly_facts" in sql
    facts = sql.split("CREATE TABLE quality.cost_monthly_facts", 1)[1].split(";", 1)[0]
    assert "UNIQUE (reporting_year, reporting_month)" in facts
    assert "sales_revenue NUMERIC," in facts
    assert "scrap_loss_per_lb >= 0" in facts
    # Inputs only: costs, totals and percentages are calculated, never stored.
    for derived in ("copq", "internal_failure", "external_failure", "pct", "total_cost"):
        assert derived not in facts.lower()
    assert "prevention" not in facts.lower() and "appraisal" not in facts.lower()
    # Schema only: nothing seeded, nothing existing altered or dropped.
    assert "INSERT" not in sql
    assert "ALTER TABLE" not in sql
    assert "DROP" not in sql
    assert "safety." not in sql


def test_cost_records_migration_creates_records_and_references_only(upgrade_sql: str) -> None:
    sql = _segment(upgrade_sql, "0010 -> 0011", "0011 -> 0012")
    assert "CREATE TABLE quality.cost_records" in sql
    assert "CREATE TABLE quality.cost_record_references" in sql
    table = sql.split("CREATE TABLE quality.cost_records", 1)[1].split(";", 1)[0]
    # Totals, net cost, days open and the record number are derived, never stored.
    for derived in ("total_cost", "net_cost", "days_open", "record_number", "copq", "good_coq"):
        assert derived not in table
    assert "material_cost NUMERIC," in table
    assert "REFERENCES safety.areas (id) ON DELETE RESTRICT" in table
    assert "(status = 'closed') = (date_closed IS NOT NULL)" in table
    assert "split_part(category_code, '.', 1) = coq_class" in table
    assert (
        "CREATE UNIQUE INDEX uq_cost_records_source_key "
        "ON quality.cost_records (source_key) WHERE source_key IS NOT NULL"
    ) in sql
    references = sql.split("CREATE TABLE quality.cost_record_references", 1)[1].split(";", 1)[0]
    assert "REFERENCES quality.cost_records (id) ON DELETE RESTRICT" in references
    # Schema only: nothing seeded, nothing existing altered or dropped.
    assert "INSERT" not in sql.replace("UPDATE core.alembic_version", "")
    assert "ALTER TABLE" not in sql
    assert "DROP" not in sql
    assert "cost_monthly_facts" not in sql


def test_car_migration_creates_car_tables_only(upgrade_sql: str) -> None:
    sql = _segment(upgrade_sql, "0011 -> 0012")
    for table in ("cars", "car_actions", "car_why_steps", "car_approvals", "car_references"):
        assert f"CREATE TABLE quality.{table} " in sql
    cars = sql.split("CREATE TABLE quality.cars ", 1)[1].split(";", 1)[0]
    # Days open, past due, cost total and progress are derived, never stored.
    for derived in ("days_open", "past_due", "total_cost", "due_soon", "progress"):
        assert derived not in cars
    assert "UNIQUE (car_number)" in cars
    assert "REFERENCES quality.cost_records (id) ON DELETE RESTRICT" in cars
    assert "status IS NOT NULL OR source = 'legacy_import'" in cars
    assert "material_loss NUMERIC," in cars
    assert (
        "CREATE UNIQUE INDEX uq_cars_quality_cost_record_id ON quality.cars "
        "(quality_cost_record_id) WHERE quality_cost_record_id IS NOT NULL"
    ) in sql
    actions = sql.split("CREATE TABLE quality.car_actions ", 1)[1].split(";", 1)[0]
    assert "REFERENCES quality.cars (id) ON DELETE RESTRICT" in actions
    assert "completed_on IS NULL OR status = 'complete'" in actions
    # Schema only: nothing seeded, nothing existing altered or dropped.
    assert "INSERT" not in sql.replace("UPDATE core.alembic_version", "")
    assert "ALTER TABLE" not in sql
    assert "DROP" not in sql
