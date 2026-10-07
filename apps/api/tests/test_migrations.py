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
    assert "contractor" not in upgrade_sql


def test_performance_migration_seeds_legacy_definitions_only(upgrade_sql: str) -> None:
    performance_sql = upgrade_sql.split("Running upgrade 0005 -> 0006", 1)[1]
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
