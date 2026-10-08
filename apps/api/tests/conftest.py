from collections.abc import Iterator

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from postgres_support import (
    DESTRUCTIVE_MARKER,
    EMPTY_DATABASE_MARKER,
    TEST_DATABASE_MODE,
    TEST_DATABASE_URL,
    UnsafeTestDatabaseError,
    alembic_config,
    check_disposable_database,
    check_shared_database,
    current_revision,
)
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.engine import make_url

from app.db.base import ALEMBIC_VERSION_SCHEMA
from app.main import create_app


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """In shared mode, tests that need an empty or throwaway database are deselected;
    the disposable suite runs them."""
    if not TEST_DATABASE_URL or TEST_DATABASE_MODE != "shared":
        return
    kept, deselected = [], []
    for item in items:
        needs_disposable = item.get_closest_marker(
            EMPTY_DATABASE_MARKER
        ) or item.get_closest_marker(DESTRUCTIVE_MARKER)
        (deselected if needs_disposable else kept).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine for the test database (requires TEST_DATABASE_URL).

    Disposable mode migrates base -> head and back; shared mode never migrates.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    url = make_url(TEST_DATABASE_URL)
    try:
        if TEST_DATABASE_MODE == "shared":
            check_shared_database(url.database)
        elif TEST_DATABASE_MODE == "disposable":
            check_disposable_database(url.database)
        else:
            raise UnsafeTestDatabaseError(f"unknown TEST_DATABASE_MODE {TEST_DATABASE_MODE!r}")
    except UnsafeTestDatabaseError as error:
        pytest.exit(str(error), returncode=2)
    engine = create_engine(url)
    if ALEMBIC_VERSION_SCHEMA not in inspect(engine).get_schema_names():
        engine.dispose()
        pytest.exit(
            f"Test database needs schema '{ALEMBIC_VERSION_SCHEMA}'; create it as in production",
            returncode=2,
        )
    if TEST_DATABASE_MODE == "shared":
        head = ScriptDirectory.from_config(alembic_config()).get_current_head()
        with engine.connect() as connection:
            revision = current_revision(connection)
        if revision != head:
            engine.dispose()
            pytest.exit(
                f"Shared test database is at {revision}, not {head}; it is never migrated "
                "by the tests",
                returncode=2,
            )
        yield engine
        engine.dispose()
        return
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
        command.upgrade(alembic_config(connection), "head")
    yield engine
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
    engine.dispose()
