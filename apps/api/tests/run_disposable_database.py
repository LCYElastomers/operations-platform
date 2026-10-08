"""Run the PostgreSQL test suite against a freshly created, throwaway database.

    DISPOSABLE_DATABASE_ADMIN_URL=<url of a role allowed to CREATE DATABASE> \
        uv run python tests/run_disposable_database.py [pytest arguments]

Creates ``op_disposable_test_<12 hex digits>`` on the admin URL's server,
creates the managed schemas (as production does), runs pytest with
TEST_DATABASE_URL pointing at it, then drops it, also when pytest fails.
The admin URL's own database is only used to issue CREATE/DROP DATABASE.
The protected databases (operations_platform, operations_platform_test) are
never created, migrated or dropped. Credentials are never printed.
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from postgres_support import DISPOSABLE_PREFIX, check_disposable_database  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402

from app.db.base import MANAGED_SCHEMAS  # noqa: E402

ADMIN_URL_VARIABLE = "DISPOSABLE_DATABASE_ADMIN_URL"


def disposable_name() -> str:
    return check_disposable_database(f"{DISPOSABLE_PREFIX}{secrets.token_hex(6)}")


def _create(admin: URL, name: str) -> None:
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()
    engine = create_engine(admin.set(database=name))
    try:
        with engine.begin() as connection:
            for schema in sorted(MANAGED_SCHEMAS):
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        engine.dispose()


def _drop(admin: URL, name: str) -> None:
    check_disposable_database(name)
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def main(pytest_args: list[str]) -> int:
    raw = os.environ.get(ADMIN_URL_VARIABLE)
    if not raw:
        print(f"{ADMIN_URL_VARIABLE} is not set", file=sys.stderr)
        return 2
    admin = make_url(raw)
    name = disposable_name()
    print(f"Creating disposable database {name} on {admin.host}:{admin.port}")
    _create(admin, name)
    try:
        env = {
            **os.environ,
            "TEST_DATABASE_URL": admin.set(database=name).render_as_string(hide_password=False),
            "TEST_DATABASE_MODE": "disposable",
        }
        env.pop(ADMIN_URL_VARIABLE, None)
        return subprocess.call([sys.executable, "-m", "pytest", *pytest_args], env=env)  # noqa: S603
    finally:
        _drop(admin, name)
        print(f"Dropped disposable database {name}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
