"""Read-only access to the Access saved query through pyodbc.

Only SELECT statements are executed; nothing in the Access database is
modified. pyodbc is imported lazily so the rest of the connector (and its
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
# SQLSTATEs meaning "the driver does not support this connection attribute".
_UNSUPPORTED_ATTRIBUTE = frozenset({"HYC00", "HY092", "HY024", "IM001"})
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


def _braced(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def connection_string(driver: str, database_path: Path) -> str:
    return f"DRIVER={_braced(driver)};DBQ={_braced(str(database_path))};ReadOnly=1;Exclusive=0;"


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
    ) -> None:
        self._driver = driver
        self._path = database_path
        self._query = query_name
        self._odbc = odbc_module

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
        readonly_attribute = True
        try:
            try:
                connection = odbc.connect(conn_str, autocommit=True, readonly=True)
            except odbc.Error as error:
                if _sqlstate(error) not in _UNSUPPORTED_ATTRIBUTE:
                    raise
                # ReadOnly=1 in the connection string still applies.
                readonly_attribute = False
                connection = odbc.connect(conn_str, autocommit=True)
        except odbc.Error as error:
            state = _sqlstate(error)
            mismatch = state in _ARCHITECTURE_MISMATCH
            hint = (
                f" This usually means the driver and Python architectures differ "
                f"(Python is {python_architecture()})."
                if mismatch
                else ""
            )
            # Driver messages can include paths, so only the SQLSTATE is reported.
            raise OdbcUnavailableError(
                f"Could not open the Access database (SQLSTATE {state}).{hint}",
                reason="architecture_mismatch" if mismatch else "connection_failed",
                sqlstate=state,
                python_architecture=python_architecture(),
            ) from None
        try:
            yield connection, readonly_attribute
        finally:
            connection.close()

    def probe(self) -> ProbeResult:
        odbc = self._module()
        with self._connect() as (connection, readonly_attribute):
            try:
                cursor = connection.cursor()
                cursor.execute(probe_sql(self._query))
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
                    extraction_sql(self._query), window.query_start, window.query_end_exclusive
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
