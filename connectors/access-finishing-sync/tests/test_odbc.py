"""AccessRepository against a fake pyodbc module (no driver needed)."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from support import DRIVER, source_row

from access_finishing_sync.errors import ExitCode, ExtractionError, OdbcUnavailableError
from access_finishing_sync.odbc import (
    EXPECTED_COLUMNS,
    AccessRepository,
    connection_string,
    extraction_sql,
    python_architecture,
)
from access_finishing_sync.window import calculate_window

WINDOW = calculate_window(dt.date(2026, 10, 2), 3)


class FakeOdbcError(Exception):
    pass


class FakeCursor:
    def __init__(self, odbc: "FakeOdbc") -> None:
        self.odbc = odbc
        self.description: list[tuple[str]] | None = None
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, *params: Any) -> None:
        self.odbc.executed.append((sql, params))
        if self.odbc.query_error:
            raise self.odbc.query_error
        self.description = [(name,) for name in self.odbc.columns]
        self._rows = list(self.odbc.rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        self.odbc.fetchone_calls += 1
        return self._rows.pop(0) if self._rows else None

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        chunk, self._rows = self._rows[:size], self._rows[size:]
        return chunk

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, odbc: "FakeOdbc") -> None:
        self.odbc = odbc

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.odbc)

    def close(self) -> None:
        self.odbc.closed += 1


class FakeOdbc:
    Error = FakeOdbcError

    def __init__(self, **kwargs: Any) -> None:
        self.installed = [DRIVER, "SQL Server"]
        self.columns: tuple[str, ...] = EXPECTED_COLUMNS
        self.rows: list[tuple[Any, ...]] = []
        self.connect_errors: list[Exception] = []
        self.query_error: Exception | None = None
        self.connects: list[tuple[str, dict[str, Any]]] = []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchone_calls = 0
        self.closed = 0
        self.__dict__.update(kwargs)

    def drivers(self) -> list[str]:
        return list(self.installed)

    def connect(self, conn_str: str, **kwargs: Any) -> FakeConnection:
        self.connects.append((conn_str, kwargs))
        if self.connect_errors:
            raise self.connect_errors.pop(0)
        return FakeConnection(self)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "private-share" / "Finishing.accdb"
    path.parent.mkdir()
    path.write_bytes(b"not a real database")
    return path


def repository(database: Path, odbc: FakeOdbc) -> AccessRepository:
    return AccessRepository(DRIVER, database, "qryFINISHING-AVG", odbc_module=odbc)


def test_connection_string_is_read_only_and_escaped() -> None:
    conn_str = connection_string(DRIVER, Path("C:/Data/odd}name;x.accdb"))

    assert conn_str.startswith("DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};")
    assert "DBQ={C:" in conn_str
    assert "odd}}name;x.accdb}" in conn_str
    assert "ReadOnly=1;" in conn_str


def test_extraction_sql_is_parameterized_with_an_exclusive_upper_bound() -> None:
    sql = extraction_sql("qryFINISHING-AVG")

    assert sql == (
        "SELECT [DATE], [CAMPNO], [LOT], [Location], [PRODUCT], [AvgOfMOISTURE], [AvgOfCOLOR], "
        "[AvgOfCombined_BD] FROM [qryFINISHING-AVG] WHERE [DATE] >= ? AND [DATE] < ? "
        "ORDER BY [DATE], [CAMPNO], [LOT], [Location], [PRODUCT]"
    )


def test_extract_queries_the_window_read_only(database: Path) -> None:
    rows = [source_row(lot=f"L{i}") for i in range(2500)]
    odbc = FakeOdbc(rows=rows)

    extraction = repository(database, odbc).extract(WINDOW)

    assert extraction.rows == rows
    assert extraction.readonly_attribute is True
    ((conn_str, kwargs),) = odbc.connects
    assert kwargs == {"autocommit": True, "readonly": True}
    assert "ReadOnly=1" in conn_str
    ((sql, params),) = odbc.executed
    assert sql.startswith("SELECT ")
    assert params == (dt.datetime(2026, 9, 30), dt.datetime(2026, 10, 3))
    assert odbc.closed == 1


def test_read_only_attribute_fallback_keeps_the_read_only_connection_string(
    database: Path,
) -> None:
    odbc = FakeOdbc(connect_errors=[FakeOdbcError("HYC00", "Optional feature not implemented")])

    extraction = repository(database, odbc).extract(WINDOW)

    assert extraction.readonly_attribute is False
    assert [kwargs for _, kwargs in odbc.connects] == [
        {"autocommit": True, "readonly": True},
        {"autocommit": True},
    ]
    assert all("ReadOnly=1" in conn_str for conn_str, _ in odbc.connects)


def test_only_select_statements_are_executed(database: Path) -> None:
    odbc = FakeOdbc(rows=[source_row()])
    repo = repository(database, odbc)

    repo.probe()
    repo.extract(WINDOW)

    assert all(sql.startswith("SELECT ") for sql, _ in odbc.executed)


def test_unexpected_columns_fail_extraction(database: Path) -> None:
    odbc = FakeOdbc(columns=("DATE", "LOT"))

    with pytest.raises(ExtractionError) as caught:
        repository(database, odbc).extract(WINDOW)

    assert caught.value.reason == "unexpected_columns"


def test_query_failure_reports_only_the_sqlstate(database: Path) -> None:
    odbc = FakeOdbc(query_error=FakeOdbcError("42S02", f"Cannot find {database}"))

    with pytest.raises(ExtractionError) as caught:
        repository(database, odbc).extract(WINDOW)

    assert caught.value.exit_code == ExitCode.EXTRACTION
    assert caught.value.fields["sqlstate"] == "42S02"
    assert str(database.parent) not in caught.value.message


def test_missing_driver_reports_the_architecture(database: Path) -> None:
    odbc = FakeOdbc(installed=["SQL Server", "Microsoft Access Driver (*.mdb)"])

    with pytest.raises(OdbcUnavailableError) as caught:
        repository(database, odbc).probe()

    error = caught.value
    assert error.reason == "driver_not_found"
    assert error.exit_code == ExitCode.ODBC_UNAVAILABLE
    assert python_architecture() in error.message
    assert "Microsoft Access Driver (*.mdb)" in error.message
    assert str(database.parent) not in error.message
    assert odbc.connects == []


@pytest.mark.parametrize("state", ["IM002", "IM014"])
def test_architecture_mismatch_is_reported_clearly(database: Path, state: str) -> None:
    odbc = FakeOdbc(connect_errors=[FakeOdbcError(state, f"Data source name not found {database}")])

    with pytest.raises(OdbcUnavailableError) as caught:
        repository(database, odbc).probe()

    assert caught.value.reason == "architecture_mismatch"
    assert "architectures differ" in caught.value.message
    assert str(database.parent) not in caught.value.message


def test_missing_database_file_reports_only_its_name(tmp_path: Path) -> None:
    path = tmp_path / "private-share" / "Missing.accdb"

    with pytest.raises(OdbcUnavailableError) as caught:
        repository(path, FakeOdbc()).probe()

    assert caught.value.reason == "database_not_found"
    assert "Missing.accdb" in caught.value.message
    assert "private-share" not in caught.value.message


def test_probe_retrieves_at_most_one_row_and_no_values(database: Path) -> None:
    odbc = FakeOdbc(rows=[source_row(lot="LOT-VALUE-1"), source_row()])

    probe = repository(database, odbc).probe()

    ((sql, params),) = odbc.executed
    assert sql == "SELECT TOP 1 * FROM [qryFINISHING-AVG]"
    assert params == ()
    assert odbc.fetchone_calls == 1
    assert probe.row_retrieved is True
    assert probe.missing_columns == ()
    assert "LOT-VALUE-1" not in repr(probe)


def test_probe_reports_missing_columns(database: Path) -> None:
    odbc = FakeOdbc(columns=("date", "CAMPNO", "LOT", "PRODUCT"))

    probe = repository(database, odbc).probe()

    assert probe.missing_columns == ("Location", "AvgOfMOISTURE", "AvgOfCOLOR", "AvgOfCombined_BD")


def test_unselectable_query_is_an_odbc_problem(database: Path) -> None:
    odbc = FakeOdbc(query_error=FakeOdbcError("42S02", "no such query"))

    with pytest.raises(OdbcUnavailableError) as caught:
        repository(database, odbc).probe()

    assert caught.value.reason == "query_unavailable"


def test_missing_pyodbc_is_an_odbc_problem(database: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pyodbc":
            raise ImportError("DLL load failed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(OdbcUnavailableError) as caught:
        AccessRepository(DRIVER, database, "qryFINISHING-AVG").probe()

    assert caught.value.reason == "pyodbc_unavailable"
