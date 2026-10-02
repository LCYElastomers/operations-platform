from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "operations-platform-api"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # SQLAlchemy URL for the host-managed PostgreSQL instance, e.g.
    # postgresql+psycopg://user:password@host.docker.internal:5432/operations
    # Kept as SecretStr so it is never rendered in logs or reprs.
    database_url: SecretStr | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_database_url_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
