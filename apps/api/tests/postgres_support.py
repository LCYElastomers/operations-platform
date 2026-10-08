"""Shared helpers for PostgreSQL integration tests (enabled by TEST_DATABASE_URL).

Two modes, chosen by TEST_DATABASE_MODE:

- ``disposable`` (default): the session migrates the database down to base and
  back up, so it must be a throwaway database. Only generated names
  (``DISPOSABLE_PREFIX`` + hex) are accepted; ``run_disposable_database.py``
  creates one, runs the suite and drops it.
- ``shared``: the populated shared test database. Nothing is migrated; it
  must already be at head, and tests marked ``empty_database`` or
  ``destructive`` are deselected (they run in the disposable suite).

``operations_platform`` is refused in both modes.
"""

import os
import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection

from app.db.base import ALEMBIC_VERSION_SCHEMA, ALEMBIC_VERSION_TABLE

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_DATABASE_MODE = os.environ.get("TEST_DATABASE_MODE", "disposable")

PRODUCTION_DATABASE = "operations_platform"
SHARED_TEST_DATABASE = "operations_platform_test"
PROTECTED_DATABASES = frozenset({PRODUCTION_DATABASE, SHARED_TEST_DATABASE})
DISPOSABLE_PREFIX = "op_disposable_test_"
_DISPOSABLE_NAME = re.compile(rf"^{DISPOSABLE_PREFIX}[0-9a-f]{{12}}$")

# Markers for tests that cannot run against the populated shared database.
EMPTY_DATABASE_MARKER = "empty_database"
DESTRUCTIVE_MARKER = "destructive"

requires_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; PostgreSQL tests skipped"
)

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


class UnsafeTestDatabaseError(Exception):
    pass


def check_disposable_database(name: str | None) -> str:
    """A database the suite may wipe: a generated disposable name, never a protected one."""
    if not name or name in PROTECTED_DATABASES:
        raise UnsafeTestDatabaseError(
            f"refusing to migrate or wipe {name!r}: it is a protected database"
        )
    if not _DISPOSABLE_NAME.match(name):
        raise UnsafeTestDatabaseError(
            f"refusing to migrate or wipe {name!r}: disposable databases are named "
            f"{DISPOSABLE_PREFIX}<12 hex digits>"
        )
    return name


def check_shared_database(name: str | None) -> str:
    """The populated shared test database, used read-only or in rolled-back transactions."""
    if name != SHARED_TEST_DATABASE:
        raise UnsafeTestDatabaseError(
            f"refusing {name!r}: shared mode runs only against {SHARED_TEST_DATABASE}"
        )
    return name


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
