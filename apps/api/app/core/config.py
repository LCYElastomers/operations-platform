from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.permissions import Permission

# Identifiers that appear in logs (connector IDs, source systems, batch IDs)
# are restricted to characters that cannot break log lines.
SAFE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,99}$"
MAX_SECRETS_PER_CONNECTOR = 5

SecretDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SafeName = Annotated[str, Field(pattern=SAFE_NAME_PATTERN)]


class ConnectorCredentials(BaseModel):
    """Verification data for one machine connector. Holds digests, never secrets.

    Several digests may be active at once so a secret can be rotated without
    downtime: add the new digest, switch the connector, remove the old one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    secret_sha256: Annotated[
        list[SecretDigest], Field(min_length=1, max_length=MAX_SECRETS_PER_CONNECTOR)
    ]
    source_systems: Annotated[list[SafeName], Field(min_length=1)]


class Settings(BaseSettings):
    # Validation errors must not echo raw values such as DATABASE_URL credentials.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_name: str = "operations-platform-api"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # SQLAlchemy URL for the host-managed PostgreSQL instance, e.g.
    # postgresql+psycopg://user:password@host.docker.internal:5432/operations
    # Kept as SecretStr so it is never rendered in logs or reprs.
    database_url: SecretStr | None = None

    # Where the moisture API reads from. "fixture" serves the labeled
    # development fixture (refused in production); "database" reads current
    # versions from quality.finishing_measurements.
    moisture_data_source: Literal["fixture", "database"] = "fixture"

    # Machine ingestion endpoints:
    #   disabled                     every request is refused (default)
    #   connector                    connector ID + secret, verified against
    #                                INGESTION_CONNECTORS
    #   development-unauthenticated  no credentials; refused in production
    ingestion_auth_mode: Literal["disabled", "connector", "development-unauthenticated"] = (
        "disabled"
    )
    # JSON object: connector ID -> {"secret_sha256": [...], "source_systems": [...]}
    ingestion_connectors: dict[SafeName, ConnectorCredentials] = {}

    # Interactive user endpoints (for example Safety data entry). No login exists yet:
    #   disabled                     requests are anonymous; protected endpoints answer 401
    #   development-unauthenticated  requests act as a fixed development user holding
    #                                DEVELOPMENT_USER_PERMISSIONS; refused in production
    user_auth_mode: Literal["disabled", "development-unauthenticated"] = "disabled"
    # JSON list of permission names granted to the development user.
    development_user_permissions: list[Permission] = [
        Permission.SAFETY_VIEW,
        Permission.SAFETY_EDIT,
        Permission.QUALITY_VIEW,
    ]

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_database_url_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ingestion_connectors", mode="before")
    @classmethod
    def _blank_connectors_are_empty(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return {}
        return value

    @field_validator("development_user_permissions", mode="before")
    @classmethod
    def _blank_permissions_are_empty(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return []
        return value

    @model_validator(mode="after")
    def _user_auth_mode_is_safe(self) -> Self:
        if (
            self.user_auth_mode == "development-unauthenticated"
            and self.environment == "production"
        ):
            raise ValueError(
                "USER_AUTH_MODE=development-unauthenticated is not allowed in production"
            )
        return self

    @model_validator(mode="after")
    def _moisture_source_is_safe(self) -> Self:
        if self.moisture_data_source == "fixture" and self.environment == "production":
            raise ValueError(
                "MOISTURE_DATA_SOURCE=fixture is not allowed in production; use database"
            )
        if self.moisture_data_source == "database" and self.database_url is None:
            raise ValueError("MOISTURE_DATA_SOURCE=database requires DATABASE_URL")
        return self

    @model_validator(mode="after")
    def _ingestion_mode_is_safe(self) -> Self:
        digests = [d for c in self.ingestion_connectors.values() for d in c.secret_sha256]
        if len(digests) != len(set(digests)):
            raise ValueError("INGESTION_CONNECTORS must not reuse a secret digest")
        if self.ingestion_auth_mode == "disabled":
            return self
        if self.ingestion_auth_mode == "development-unauthenticated":
            if self.environment == "production":
                raise ValueError(
                    "INGESTION_AUTH_MODE=development-unauthenticated is not allowed in production"
                )
        elif not self.ingestion_connectors:
            raise ValueError("INGESTION_AUTH_MODE=connector requires INGESTION_CONNECTORS")
        if self.database_url is None:
            raise ValueError("Enabling ingestion requires DATABASE_URL")
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
