"""Connector configuration from a local TOML file and environment variables.

Environment variables override file values. The connector secret is never part
of this configuration; see credentials.py.
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from access_finishing_sync.errors import ConfigError

CONFIG_FILE_VARIABLE = "ACCESS_SYNC_CONFIG"
INGESTION_PATH = "/api/v1/ingestion/quality/finishing/batches"
MAX_SERVER_BATCH_ROWS = 5000
# Mirrors the API's sourceSystem / batchId rule.
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,99}")
# batchId = <source>:<connector>:<YYYYMMDDTHHMMSSZ>:<32 hex>, at most 100 chars.
MAX_IDENTITY_LENGTH = 100 - (3 + 16 + 32)
DEVELOPMENT_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1"})
SECRET_SOURCES = ("credential-manager", "environment")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_LIKE_KEY = re.compile(r"SECRET|PASSWORD|TOKEN|CREDENTIAL_VALUE|BEARER", re.IGNORECASE)

SecretSource = Literal["credential-manager", "environment"]

DEFAULTS: dict[str, str] = {
    "CONNECTOR_ID": "lcy-access-sync",
    "ACCESS_QUERY_NAME": "qryFINISHING-AVG",
    "SOURCE_SYSTEM": "access-qryFINISHING-AVG",
    "RECONCILIATION_DAYS": "60",
    "BATCH_SIZE": "5000",
    "HTTP_CONNECT_TIMEOUT_SECONDS": "10",
    "HTTP_READ_TIMEOUT_SECONDS": "120",
    "HTTP_MAX_ATTEMPTS": "5",
    "DEVELOPMENT_MODE": "false",
    "SECRET_SOURCE": "credential-manager",
    "LOG_MAX_BYTES": str(10 * 1024 * 1024),
    "LOG_BACKUP_COUNT": "10",
}
REQUIRED = (
    "API_BASE_URL",
    "ACCESS_DATABASE_PATH",
    "ACCESS_ODBC_DRIVER",
    "LOG_DIRECTORY",
    "LOCK_DIRECTORY",
)
KNOWN_KEYS = frozenset({*DEFAULTS, *REQUIRED, "CREDENTIAL_TARGET"})


@dataclass(frozen=True)
class Config:
    api_base_url: str
    connector_id: str
    access_database_path: Path
    access_odbc_driver: str
    access_query_name: str
    source_system: str
    reconciliation_days: int
    batch_size: int
    http_connect_timeout_seconds: float
    http_read_timeout_seconds: float
    http_max_attempts: int
    log_directory: Path
    lock_directory: Path
    development_mode: bool
    secret_source: SecretSource
    credential_target: str
    log_max_bytes: int
    log_backup_count: int

    @property
    def ingestion_url(self) -> str:
        return self.api_base_url.rstrip("/") + INGESTION_PATH

    @property
    def api_host(self) -> str:
        return urlsplit(self.api_base_url).hostname or ""


def default_credential_target(connector_id: str) -> str:
    return f"operations-platform/{connector_id}"


def read_config_file(path: Path) -> dict[str, str]:
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError("Configuration file not found.", config_file=str(path)) from None
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(
            f"Configuration file could not be read ({type(error).__name__}).",
            config_file=str(path),
        ) from None

    values: dict[str, str] = {}
    problems: list[str] = []
    for key, value in document.items():
        if key not in KNOWN_KEYS:
            if _SECRET_LIKE_KEY.search(key):
                problems.append(
                    f"{key}: secrets must not be stored in the configuration file; "
                    "use Windows Credential Manager"
                )
            else:
                problems.append(f"{key}: unknown setting")
        elif isinstance(value, bool):
            values[key] = "true" if value else "false"
        elif isinstance(value, str | int | float):
            values[key] = str(value)
        else:
            problems.append(f"{key}: must be a string, number, or boolean")
    if problems:
        raise ConfigError("Invalid configuration file: " + "; ".join(problems))
    return values


def load_config(environ: Mapping[str, str], config_file: Path | None = None) -> Config:
    """Merge defaults, file values, and environment variables, then validate."""
    raw = dict(DEFAULTS)
    if config_file is not None:
        raw.update(read_config_file(config_file))
    raw.update({key: environ[key] for key in KNOWN_KEYS if environ.get(key, "") != ""})
    return _validate(raw)


class _Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, message: str) -> None:
        self.items.append(message)


def _text(raw: Mapping[str, str], key: str, problems: _Problems, max_length: int = 1000) -> str:
    value = raw.get(key, "").strip()
    if not value:
        problems.add(f"{key} is required")
    elif len(value) > max_length or _CONTROL.search(value):
        problems.add(f"{key} must be at most {max_length} characters without control characters")
    return value


def _integer(raw: Mapping[str, str], key: str, low: int, high: int, problems: _Problems) -> int:
    value = raw.get(key, "").strip()
    if re.fullmatch(r"\d{1,12}", value) and low <= int(value) <= high:
        return int(value)
    problems.add(f"{key} must be an integer between {low} and {high}")
    return low


def _seconds(raw: Mapping[str, str], key: str, high: float, problems: _Problems) -> float:
    value = raw.get(key, "").strip()
    if re.fullmatch(r"\d{1,6}(\.\d{1,3})?", value) and 0 < float(value) <= high:
        return float(value)
    problems.add(f"{key} must be a number of seconds greater than 0 and at most {high:g}")
    return 1.0


def _boolean(raw: Mapping[str, str], key: str, problems: _Problems) -> bool:
    value = raw.get(key, "").strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    problems.add(f"{key} must be true or false")
    return False


def _safe_name(raw: Mapping[str, str], key: str, problems: _Problems) -> str:
    value = raw.get(key, "").strip()
    if not SAFE_NAME.fullmatch(value):
        problems.add(
            f"{key} must be 1-100 characters: letters, digits, '.', '_', ':', '-', "
            "starting with a letter or digit"
        )
    return value


def _absolute_path(raw: Mapping[str, str], key: str, problems: _Problems) -> Path:
    value = _text(raw, key, problems)
    path = Path(value)
    if value and not path.is_absolute():
        problems.add(f"{key} must be an absolute path")
    return path


def _api_base_url(value: str, development_mode: bool, problems: _Problems) -> None:
    if not value:
        return
    parts = urlsplit(value)
    # Messages never echo the URL: it could contain credentials.
    if "@" in parts.netloc:
        problems.add("API_BASE_URL must not contain user names or passwords")
        return
    if parts.query or parts.fragment:
        problems.add("API_BASE_URL must not contain a query string or fragment")
    host = (parts.hostname or "").lower()
    if not host:
        problems.add("API_BASE_URL must include a host name")
    if parts.scheme == "https":
        return
    if parts.scheme == "http" and development_mode and host in DEVELOPMENT_HTTP_HOSTS:
        return
    problems.add(
        "API_BASE_URL must use https:// (plain http:// is allowed only with "
        "DEVELOPMENT_MODE=true and host localhost or 127.0.0.1)"
    )


def _validate(raw: Mapping[str, str]) -> Config:
    problems = _Problems()

    development_mode = _boolean(raw, "DEVELOPMENT_MODE", problems)
    api_base_url = _text(raw, "API_BASE_URL", problems)
    _api_base_url(api_base_url, development_mode, problems)

    connector_id = _safe_name(raw, "CONNECTOR_ID", problems)
    source_system = _safe_name(raw, "SOURCE_SYSTEM", problems)
    if len(connector_id) + len(source_system) > MAX_IDENTITY_LENGTH:
        problems.add(
            f"CONNECTOR_ID and SOURCE_SYSTEM together must be at most "
            f"{MAX_IDENTITY_LENGTH} characters so batch IDs fit the API limit"
        )

    database_path = _absolute_path(raw, "ACCESS_DATABASE_PATH", problems)
    if database_path.suffix.lower() not in {".accdb", ".mdb"}:
        problems.add("ACCESS_DATABASE_PATH must name an .accdb or .mdb file")
    if any(c in str(database_path) for c in ";{}"):
        problems.add("ACCESS_DATABASE_PATH must not contain ';', '{' or '}'")

    driver = _text(raw, "ACCESS_ODBC_DRIVER", problems, max_length=200)
    if any(c in driver for c in "{};"):
        problems.add("ACCESS_ODBC_DRIVER must not contain '{', '}' or ';'")

    query_name = _text(raw, "ACCESS_QUERY_NAME", problems, max_length=64)
    if any(c in query_name for c in "[]`!"):
        problems.add("ACCESS_QUERY_NAME must not contain '[', ']', '`' or '!'")

    secret_source = raw.get("SECRET_SOURCE", "").strip()
    if secret_source not in SECRET_SOURCES:
        problems.add("SECRET_SOURCE must be 'credential-manager' or 'environment'")
    elif secret_source == "environment" and not development_mode:  # noqa: S105 - a mode name
        problems.add(
            "SECRET_SOURCE=environment is for development and testing only and "
            "requires DEVELOPMENT_MODE=true; use credential-manager in production"
        )

    credential_target = raw.get("CREDENTIAL_TARGET", "").strip() or default_credential_target(
        connector_id
    )
    if len(credential_target) > 256 or _CONTROL.search(credential_target):
        problems.add("CREDENTIAL_TARGET must be at most 256 characters without control characters")

    config: dict[str, Any] = {
        "api_base_url": api_base_url,
        "connector_id": connector_id,
        "access_database_path": database_path,
        "access_odbc_driver": driver,
        "access_query_name": query_name,
        "source_system": source_system,
        "reconciliation_days": _integer(raw, "RECONCILIATION_DAYS", 1, 3660, problems),
        "batch_size": _integer(raw, "BATCH_SIZE", 1, MAX_SERVER_BATCH_ROWS, problems),
        "http_connect_timeout_seconds": _seconds(
            raw, "HTTP_CONNECT_TIMEOUT_SECONDS", 300, problems
        ),
        "http_read_timeout_seconds": _seconds(raw, "HTTP_READ_TIMEOUT_SECONDS", 900, problems),
        "http_max_attempts": _integer(raw, "HTTP_MAX_ATTEMPTS", 1, 10, problems),
        "log_directory": _absolute_path(raw, "LOG_DIRECTORY", problems),
        "lock_directory": _absolute_path(raw, "LOCK_DIRECTORY", problems),
        "development_mode": development_mode,
        "secret_source": secret_source,
        "credential_target": credential_target,
        "log_max_bytes": _integer(raw, "LOG_MAX_BYTES", 64 * 1024, 1024**3, problems),
        "log_backup_count": _integer(raw, "LOG_BACKUP_COUNT", 1, 100, problems),
    }
    if problems.items:
        raise ConfigError("Invalid configuration: " + "; ".join(problems.items))
    return Config(**config)
