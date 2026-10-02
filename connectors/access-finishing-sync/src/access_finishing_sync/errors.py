"""Process exit codes and the errors that map to them.

Error messages and fields are logged, so they must never contain the
connector secret, request bodies, or source row values.
"""

from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIGURATION = 2
    LOCK_ACTIVE = 3
    ODBC_UNAVAILABLE = 4
    EXTRACTION = 5
    AUTHENTICATION = 6
    API_REJECTED = 7
    TRANSIENT = 8
    PARTIAL_ACCEPTANCE = 9
    INTERNAL = 10


class ConnectorError(Exception):
    exit_code = ExitCode.INTERNAL

    def __init__(self, message: str, *, reason: str, **fields: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.fields = fields


class ConfigError(ConnectorError):
    exit_code = ExitCode.CONFIGURATION

    def __init__(self, message: str, *, reason: str = "invalid_configuration", **fields: Any):
        super().__init__(message, reason=reason, **fields)


class LockActiveError(ConnectorError):
    exit_code = ExitCode.LOCK_ACTIVE


class OdbcUnavailableError(ConnectorError):
    exit_code = ExitCode.ODBC_UNAVAILABLE


class ExtractionError(ConnectorError):
    exit_code = ExitCode.EXTRACTION


class AuthenticationError(ConnectorError):
    exit_code = ExitCode.AUTHENTICATION


class ApiRejectedError(ConnectorError):
    exit_code = ExitCode.API_REJECTED


class TransientFailureError(ConnectorError):
    exit_code = ExitCode.TRANSIENT


class UnexpectedResponseError(ConnectorError):
    exit_code = ExitCode.INTERNAL
