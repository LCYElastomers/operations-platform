"""Whether the database schema matches the migrations shipped with this code."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

from app.db.base import ALEMBIC_VERSION_SCHEMA, ALEMBIC_VERSION_TABLE

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@dataclass(frozen=True)
class SchemaState:
    current: tuple[str, ...]
    head: str

    @property
    def at_head(self) -> bool:
        return self.current == (self.head,)


@cache
def head_revision() -> str:
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    if head is None:
        raise RuntimeError("No migrations are shipped with this code.")
    return head


def schema_state(connection: Connection) -> SchemaState:
    current = MigrationContext.configure(
        connection,
        opts={
            "version_table": ALEMBIC_VERSION_TABLE,
            "version_table_schema": ALEMBIC_VERSION_SCHEMA,
        },
    ).get_current_heads()
    return SchemaState(current=tuple(current), head=head_revision())
