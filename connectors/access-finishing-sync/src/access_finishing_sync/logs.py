"""Structured JSON-lines logging with rotation and redaction.

Events carry only operational metadata. As defence in depth the formatter
redacts the connector secret, bearer tokens, and sensitive field names from
every line, even if one were passed by mistake. Tracebacks are not written
(driver and HTTP exception text can contain paths or values); only the
exception type is.
"""

import datetime as dt
import json
import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Any, TextIO

LOGGER_NAME = "access_finishing_sync"
LOG_FILE_NAME = "access-finishing-sync.log"
REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {"authorization", "secret", "password", "token", "headers", "body", "payload", "rows"}
)
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s\"',;]+")
_GENERATED_TOKEN = re.compile(r"\bopc_[A-Za-z0-9_\-]{8,}")


class Redactor:
    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def add(self, secret: str) -> None:
        if secret:
            self._secrets.add(secret)

    def redact(self, text: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, REDACTED)
            # The same value as it would appear inside a JSON string.
            text = text.replace(json.dumps(secret)[1:-1], REDACTED)
        text = _BEARER.sub(f"Bearer {REDACTED}", text)
        return _GENERATED_TOKEN.sub(REDACTED, text)


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        key: REDACTED if key.lower() in SENSITIVE_KEYS else value for key, value in fields.items()
    }


class JsonFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        document.update(_clean(getattr(record, "fields", {})))
        if record.exc_info and record.exc_info[0] is not None:
            document["exception_type"] = record.exc_info[0].__name__
        return self._redactor.redact(json.dumps(document, default=str, ensure_ascii=True))


class RunLogger:
    """Adds run identity to every event."""

    def __init__(self, logger: logging.Logger, **context: Any) -> None:
        self._logger = logger
        self.context = context

    def _log(self, level: int, event: str, fields: dict[str, Any]) -> None:
        self._logger.log(level, event, extra={"fields": {**self.context, **fields}})

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, fields)


def configure_logging(
    redactor: Redactor,
    *,
    log_directory: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 10,
    stream: TextIO | None = None,
) -> logging.Logger:
    """JSON lines to stderr and, if a directory is given, to a rotating file."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = JsonFormatter(redactor)

    console = logging.StreamHandler(stream or sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_directory is not None:
        log_directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_directory / LOG_FILE_NAME,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Third-party libraries must not write request details anywhere.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return logger
