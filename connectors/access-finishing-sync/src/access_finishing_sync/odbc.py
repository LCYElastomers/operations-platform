"""Read-only access to the Access saved query through pyodbc.

Only SELECT statements are executed; nothing in the Access database is
modified. Every connection string carries ReadOnly=1. The connection first
also requests the ODBC read-only access-mode attribute; if the driver rejects
that attribute, it is retried exactly once without it (ReadOnly=1 still
applies). pyodbc is imported lazily so the rest of the connector (and its
tests) work without an ODBC driver manager.
"""

import re
import struct
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from access_finishing_sync.errors import ExtractionError, OdbcUnavailableError
from access_finishing_sync.logs import RunLogger
from access_finishing_sync.window import DateWindow

EXPECTED_COLUMNS = (
    "DATE",
    "CAMPNO",
    "LOT",
    "Location",
    "PRODUCT",
    "AvgOfMOISTURE",
    "AvgOfCOLOR",
    "AvgOfCombined_BD",
)
FETCH_CHUNK = 1000
# SQLSTATEs meaning the driver rejected or does not support the ODBC
# access-mode attribute: optional feature not implemented, invalid attribute
# identifier, invalid attribute value, driver does not support this function.
ACCESS_MODE_REJECTED = frozenset({"HYC00", "HY092", "HY024", "IM001"})
# Characters that would need ODBC brace quoting in DBQ; refused instead, so the
# connection string keeps the plain form the Access driver is known to accept.
UNSAFE_PATH_CHARACTERS = frozenset(";{}")
_ARCHITECTURE_MISMATCH = frozenset({"IM002", "IM014"})
_SQLSTATE = re.compile(r"[0-9A-Z]{5}")


def python_architecture() -> str:
    return f"{struct.calcsize('P') * 8}-bit"


def other_architecture() -> str:
    return "32-bit" if python_architecture() == "64-bit" else "64-bit"


def _sqlstate(error: BaseException) -> str:
    args = getattr(error, "args", ())
    if args and isinstance(args[0], str) and _SQLSTATE.fullmatch(args[0]):
        return args[0]
    return "unknown"


def connection_string(driver: str, database_path: Path) -> str:
    """Always includes ReadOnly=1; there is no variant without it."""
    path = str(database_path)
    if any(c in UNSAFE_PATH_CHARACTERS for c in path) or any(c in "{};" for c in driver):
        raise ValueError("driver name or database path contains ';', '{' or '}'")
    return f"DRIVER={{{driver}}};DBQ={path};ReadOnly=1;"


def _require_select(sql: str) -> str:
    # The repository never issues anything but a single SELECT statement.
    if not sql.startswith("SELECT ") or ";" in sql:
        raise RuntimeError("only single SELECT statements may be executed against Access")
    return sql


def _columns_sql() -> str:
    return ", ".join(f"[{name}]" for name in EXPECTED_COLUMNS)


# The query name is configuration validated to contain no bracket characters;
# the date bounds are always bound parameters.
def extraction_sql(query_name: str) -> str:
    return (
        f"SELECT {_columns_sql()} FROM [{query_name}] "  # noqa: S608
        "WHERE [DATE] >= ? AND [DATE] < ? "
        "ORDER BY [DATE], [CAMPNO], [LOT], [Location], [PRODUCT]"
    )


def probe_sql(query_name: str) -> str:
    return f"SELECT TOP 1 * FROM [{query_name}]"  # noqa: S608


@dataclass(frozen=True)
class ProbeResult:
    python_architecture: str
    columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    row_retrieved: bool
    readonly_attribute: bool


@dataclass(frozen=True)
class Extraction:
    rows: list[tuple[Any, ...]]
    readonly_attribute: bool


class SourceRepository(Protocol):
    def probe(self) -> ProbeResult: ...

    def extract(self, window: DateWindow) -> Extraction: ...


class AccessRepository:
    def __init__(
        self,
        driver: str,
        database_path: Path,
        query_name: str,
        odbc_module: ModuleType | Any | None = None,
        log: RunLogger | None = None,
    ) -> None:
        self._driver = driver
        self._path = database_path
        self._query = query_name
        self._odbc = odbc_module
        self._log = log

    def _module(self) -> Any:
        if self._odbc is None:
            try:
                import pyodbc
            except ImportError as error:
                raise OdbcUnavailableError(
                    f"pyodbc could not be loaded ({type(error).__name__}).",
                    reason="pyodbc_unavailable",
                ) from None
            self._odbc = pyodbc
        return self._odbc

    def check_driver(self) -> None:
        drivers = list(self._module().drivers())
        if self._driver in drivers:
            return
        visible = sorted(d for d in drivers if "access" in d.lower())
        raise OdbcUnavailableError(
            f"ODBC driver '{self._driver}' is not available to this {python_architecture()} "
            f"Python. Access drivers visible to this process: {visible or 'none'}. A driver "
            f"installed only for {other_architecture()} applications is invisible here: install "
            f"the {python_architecture()} Microsoft Access Database Engine, or run the "
            f"connector with {other_architecture()} Python.",
            reason="driver_not_found",
            python_architecture=python_architecture(),
            visible_access_drivers=visible,
        )

    def check_database_file(self) -> None:
        # Only the file name is reported; the full path is configuration metadata.
        if not self._path.is_file():
            raise OdbcUnavailableError(
                f"Access database file '{self._path.name}' was not found or is not a file "
                "(check ACCESS_DATABASE_PATH and the account's read permission on the folder).",
                reason="database_not_found",
                database_file=self._path.name,
            )

    @contextmanager
    def _connect(self) -> Iterator[tuple[Any, bool]]:
        odbc = self._module()
        self.check_driver()
        self.check_database_file()
        conn_str = connection_string(self._driver, self._path)

        try:
            connection = odbc.connect(conn_str, autocommit=True, readonly=True)
            readonly_attribute = True
            rejected_state = None
        except odbc.Error as error:
            rejected_state = _sqlstate(error)
            if rejected_state not in ACCESS_MODE_REJECTED:
                raise self._open_failed(rejected_state, attempt="access_mode_attribute") from None
            self._event(
                "odbc_access_mode_attribute_rejected",
                sqlstate=rejected_state,
                retrying_with="ReadOnly=1 connection string only",
            )
            # Exactly one retry, with the same connection string (ReadOnly=1).
            try:
                connection = odbc.connect(conn_str, autocommit=True)
            except odbc.Error as retry_error:
                raise self._open_failed(
                    _sqlstate(retry_error),
                    attempt="connection_string_only",
                    access_mode_sqlstate=rejected_state,
                ) from None
            readonly_attribute = False

        self._event(
            "odbc_connection_opened",
            readonly_attribute=readonly_attribute,
            readonly_connection_string=True,
            access_mode_sqlstate=rejected_state,
            database_file=self._path.name,
        )
        try:
            yield connection, readonly_attribute
        finally:
            connection.close()

    def _event(self, event: str, **fields: Any) -> None:
        if self._log is not None:
            self._log.info(event, **fields)

    def _open_failed(self, state: str, *, attempt: str, **fields: Any) -> OdbcUnavailableError:
        mismatch = state in _ARCHITECTURE_MISMATCH
        hint = (
            f" This usually means the driver and Python architectures differ "
            f"(Python is {python_architecture()})."
            if mismatch
            else ""
        )
        retried = (
            f" The first attempt, with the ODBC read-only access-mode attribute, was "
            f"rejected (SQLSTATE {fields['access_mode_sqlstate']}); the retry with only "
            f"ReadOnly=1 in the connection string also failed."
            if attempt == "connection_string_only"
            else ""
        )
        # Driver messages can include paths, so only SQLSTATEs and the file name are reported.
        return OdbcUnavailableError(
            f"Could not open the Access database '{self._path.name}' "
            f"(SQLSTATE {state}).{retried}{hint}",
            reason="architecture_mismatch" if mismatch else "connection_failed",
            sqlstate=state,
            attempt=attempt,
            database_file=self._path.name,
            python_architecture=python_architecture(),
            **fields,
        )

    def probe(self) -> ProbeResult:
        odbc = self._module()
        with self._connect() as (connection, readonly_attribute):
            try:
                cursor = connection.cursor()
                cursor.execute(_require_select(probe_sql(self._query)))
                columns = tuple(column[0] for column in cursor.description or ())
                row_retrieved = cursor.fetchone() is not None
                cursor.close()
            except odbc.Error as error:
                state = _sqlstate(error)
                raise OdbcUnavailableError(
                    f"The query '{self._query}' could not be selected (SQLSTATE {state}).",
                    reason="query_unavailable",
                    sqlstate=state,
                ) from None
        present = {name.lower() for name in columns}
        missing = tuple(name for name in EXPECTED_COLUMNS if name.lower() not in present)
        return ProbeResult(
            python_architecture=python_architecture(),
            columns=columns,
            missing_columns=missing,
            row_retrieved=row_retrieved,
            readonly_attribute=readonly_attribute,
        )

    def extract(self, window: DateWindow) -> Extraction:
        odbc = self._module()
        with self._connect() as (connection, readonly_attribute):
            try:
                cursor = connection.cursor()
                cursor.execute(
                    _require_select(extraction_sql(self._query)),
                    window.query_start,
                    window.query_end_exclusive,
                )
                _check_columns(cursor.description or ())
                rows: list[tuple[Any, ...]] = []
                while chunk := cursor.fetchmany(FETCH_CHUNK):
                    rows.extend(tuple(row) for row in chunk)
                cursor.close()
            except odbc.Error as error:
                state = _sqlstate(error)
                raise ExtractionError(
                    f"Extraction from '{self._query}' failed (SQLSTATE {state}).",
                    reason="query_failed",
                    sqlstate=state,
                ) from None
        return Extraction(rows=rows, readonly_attribute=readonly_attribute)


def _check_columns(description: Sequence[Sequence[Any]]) -> None:
    names = tuple(str(column[0]).lower() for column in description)
    if names != tuple(name.lower() for name in EXPECTED_COLUMNS):
        raise ExtractionError("The query returned unexpected columns.", reason="unexpected_columns")
