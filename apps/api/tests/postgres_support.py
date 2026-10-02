"""Shared helpers for PostgreSQL integration tests (enabled by TEST_DATABASE_URL)."""

import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection

from app.db.base import ALEMBIC_VERSION_SCHEMA, ALEMBIC_VERSION_TABLE

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; PostgreSQL tests skipped"
)

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def current_revision(connection: Connection) -> str | None:
    context = MigrationContext.configure(
        connection,
        opts={
            "version_table": ALEMBIC_VERSION_TABLE,
            "version_table_schema": ALEMBIC_VERSION_SCHEMA,
        },
    )
    return context.get_current_revision()
