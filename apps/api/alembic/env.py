from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.db.base import ALEMBIC_VERSION_SCHEMA, ALEMBIC_VERSION_TABLE, MANAGED_SCHEMAS
from app.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


# Autogenerate only inspects schemas owned by this application, so it never
# proposes changes to unrelated objects in a shared database.
def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


def _database_url() -> str:
    database_url = get_settings().database_url
    if database_url is None:
        raise RuntimeError("DATABASE_URL must be set to run migrations")
    return database_url.get_secret_value()


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        version_table=ALEMBIC_VERSION_TABLE,
        version_table_schema=ALEMBIC_VERSION_SCHEMA,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests pass an existing connection; otherwise connect using DATABASE_URL.
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
