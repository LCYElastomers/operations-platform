from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    pass


@lru_cache
def get_engine() -> Engine:
    database_url = get_settings().database_url
    if database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    return create_engine(database_url.get_secret_value(), pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    with get_sessionmaker()() as session:
        yield session
