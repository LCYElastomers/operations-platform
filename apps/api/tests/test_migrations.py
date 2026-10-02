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
    assert all(name.split(".")[0] in {"core", "quality"} for name in created), created
    assert "public." not in upgrade_sql


def test_migrations_never_create_the_core_schema(upgrade_sql: str) -> None:
    assert "CREATE SCHEMA core" not in upgrade_sql
