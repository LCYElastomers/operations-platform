from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# PostgreSQL schemas owned by this application (used by Alembic autogenerate).
MANAGED_SCHEMAS = frozenset({"quality"})


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
