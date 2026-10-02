from collections.abc import Iterator

import pytest
from alembic import command
from fastapi.testclient import TestClient
from postgres_support import TEST_DATABASE_URL, alembic_config
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.engine import make_url

from app.db.base import ALEMBIC_VERSION_SCHEMA
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine for the migrated test database (requires TEST_DATABASE_URL)."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    url = make_url(TEST_DATABASE_URL)
    if "test" not in (url.database or ""):
        pytest.exit("TEST_DATABASE_URL database name must contain 'test'", returncode=2)
    engine = create_engine(url)
    if ALEMBIC_VERSION_SCHEMA not in inspect(engine).get_schema_names():
        engine.dispose()
        pytest.exit(
            f"Test database needs schema '{ALEMBIC_VERSION_SCHEMA}'; create it as in production",
            returncode=2,
        )
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
        command.upgrade(alembic_config(connection), "head")
    yield engine
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
    engine.dispose()
