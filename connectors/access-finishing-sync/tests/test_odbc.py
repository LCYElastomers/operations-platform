"""AccessRepository against a fake pyodbc module (no driver needed)."""

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest
from support import DRIVER, Forbidden, LogCapture, make_config, make_service, source_row

from access_finishing_sync import odbc as odbc_module
from access_finishing_sync.errors import ExitCode, ExtractionError, OdbcUnavailableError
from access_finishing_sync.logs import RunLogger
from access_finishing_sync.odbc import (
    EXPECTED_COLUMNS,
    AccessRepository,
    _require_select,
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


def repository(database: Path, odbc: FakeOdbc, log: RunLogger | None = None) -> AccessRepository:
    return AccessRepository(DRIVER, database, "qryFINISHING-AVG", odbc_module=odbc, log=log)


def test_connection_string_matches_the_proven_read_only_form() -> None:
    path = PureWindowsPath(r"\\fileserver\Quality Share\Finishing.accdb")

    conn_str = connection_string(DRIVER, path)  # type: ignore[arg-type]

    assert conn_str == (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        r"DBQ=\\fileserver\Quality Share\Finishing.accdb;"
        "ReadOnly=1;"
    )


@pytest.mark.parametrize("name", ["odd;x.accdb", "odd{x.accdb", "odd}x.accdb"])
def test_connection_string_refuses_characters_needing_quoting(name: str) -> None:
    with pytest.raises(ValueError):
        connection_string(DRIVER, Path("C:/Data") / name)


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


def hy024(database: Path) -> FakeOdbcError:
    # Driver messages may echo the path; it must never reach errors or logs.
    return FakeOdbcError("HY024", f"[Microsoft][ODBC] Invalid attribute value {database}")


def test_access_mode_attribute_success_is_logged(database: Path) -> None:
    capture = LogCapture()
    odbc = FakeOdbc()

    probe = repository(database, odbc, log=capture.log).probe()

    assert probe.readonly_attribute is True
    assert [kwargs for _, kwargs in odbc.connects] == [{"autocommit": True, "readonly": True}]
    (opened,) = capture.named("odbc_connection_opened")
    assert opened["readonly_attribute"] is True
    assert opened["readonly_connection_string"] is True
    assert opened["access_mode_sqlstate"] is None
    assert opened["database_file"] == "Finishing.accdb"
    assert capture.named("odbc_access_mode_attribute_rejected") == []


@pytest.mark.parametrize("state", ["HY024", "HYC00", "HY092", "IM001"])
def test_rejected_access_mode_attribute_falls_back_once(database: Path, state: str) -> None:
    capture = LogCapture()
    odbc = FakeOdbc(connect_errors=[FakeOdbcError(state, f"rejected {database}")])

    extraction = repository(database, odbc, log=capture.log).extract(WINDOW)

    assert extraction.readonly_attribute is False
    assert [kwargs for _, kwargs in odbc.connects] == [
        {"autocommit": True, "readonly": True},
        {"autocommit": True},
    ]
    (rejected,) = capture.named("odbc_access_mode_attribute_rejected")
    assert rejected["sqlstate"] == state
    (opened,) = capture.named("odbc_connection_opened")
    assert opened["readonly_attribute"] is False
    assert opened["readonly_connection_string"] is True
    assert opened["access_mode_sqlstate"] == state


def test_fallback_retains_the_identical_read_only_connection_string(database: Path) -> None:
    odbc = FakeOdbc(connect_errors=[hy024(database)])

    repository(database, odbc).probe()

    (first, _), (second, _) = odbc.connects
    assert second == first
    assert second.endswith(";ReadOnly=1;")
    assert "Exclusive" not in second


def test_fallback_failure_reports_both_sqlstates_without_retrying_again(database: Path) -> None:
    capture = LogCapture()
    odbc = FakeOdbc(
        connect_errors=[hy024(database), FakeOdbcError("HY000", f"Could not use '{database}'")]
    )

    with pytest.raises(OdbcUnavailableError) as caught:
        repository(database, odbc, log=capture.log).probe()

    error = caught.value
    assert len(odbc.connects) == 2
    assert error.reason == "connection_failed"
    assert error.exit_code == ExitCode.ODBC_UNAVAILABLE
    assert error.fields["sqlstate"] == "HY000"
    assert error.fields["access_mode_sqlstate"] == "HY024"
    assert error.fields["attempt"] == "connection_string_only"
    assert error.fields["database_file"] == "Finishing.accdb"
    assert "HY024" in error.message and "HY000" in error.message
    assert str(database.parent) not in error.message
    assert str(database.parent) not in repr(error.fields)
    assert capture.named("odbc_connection_opened") == []
    assert odbc.executed == []


@pytest.mark.parametrize("state", ["HY000", "08001", "28000", "IM002"])
def test_unrelated_open_failures_do_not_fall_back(database: Path, state: str) -> None:
    capture = LogCapture()
    odbc = FakeOdbc(connect_errors=[FakeOdbcError(state, f"failure for {database}")])

    with pytest.raises(OdbcUnavailableError) as caught:
        repository(database, odbc, log=capture.log).probe()

    assert len(odbc.connects) == 1
    assert caught.value.fields["sqlstate"] == state
    assert caught.value.fields["attempt"] == "access_mode_attribute"
    assert "access_mode_sqlstate" not in caught.value.fields
    assert capture.named("odbc_access_mode_attribute_rejected") == []


def test_query_is_validated_after_fallback(database: Path) -> None:
    odbc = FakeOdbc(
        connect_errors=[hy024(database)],
        query_error=FakeOdbcError("42S02", "no such query"),
    )

    with pytest.raises(OdbcUnavailableError) as caught:
        repository(database, odbc).probe()

    assert caught.value.reason == "query_unavailable"
    assert len(odbc.connects) == 2


def test_columns_are_validated_after_fallback(database: Path) -> None:
    odbc = FakeOdbc(connect_errors=[hy024(database)], columns=("DATE", "LOT"))

    probe = repository(database, odbc).probe()

    assert probe.readonly_attribute is False
    assert probe.missing_columns == EXPECTED_COLUMNS[1:2] + EXPECTED_COLUMNS[3:]


def test_extraction_columns_are_validated_after_fallback(database: Path) -> None:
    odbc = FakeOdbc(connect_errors=[hy024(database)], columns=("DATE", "LOT"))

    with pytest.raises(ExtractionError) as caught:
        repository(database, odbc).extract(WINDOW)

    assert caught.value.reason == "unexpected_columns"


def check_odbc(tmp_path: Path, database: Path, odbc: FakeOdbc) -> tuple[ExitCode, LogCapture]:
    capture = LogCapture()
    config = make_config(tmp_path, ACCESS_DATABASE_PATH=str(database))
    service = make_service(
        config,
        capture,
        repository=repository(database, odbc, log=capture.log),
        transport=Forbidden("HTTP transport"),
        credentials=Forbidden("credential provider"),
        lock=Forbidden("lock"),
    )
    return service.execute("check-odbc"), capture


def test_check_odbc_succeeds_through_the_fallback(tmp_path: Path, database: Path) -> None:
    odbc = FakeOdbc(
        connect_errors=[hy024(database)],
        rows=[source_row(lot="LOT-VALUE-SECRETIVE", moisture=Decimal("0.123456789"))] * 3,
    )

    code, capture = check_odbc(tmp_path, database, odbc)

    assert code == ExitCode.SUCCESS
    assert odbc.fetchone_calls == 1
    ((sql, _),) = odbc.executed
    assert sql == "SELECT TOP 1 * FROM [qryFINISHING-AVG]"
    (probe,) = capture.named("odbc_probe")
    assert probe["readonly_attribute"] is False
    assert (probe["column_count"], probe["missing_columns"]) == (8, [])
    assert probe["test_row_retrieved"] is True
    assert "LOT-VALUE-SECRETIVE" not in capture.text
    assert "0.123456789" not in capture.text
    assert str(database.parent) not in capture.text
    assert str(database.parent).replace("\\", "\\\\") not in capture.text


def test_check_odbc_reports_missing_columns_after_fallback(tmp_path: Path, database: Path) -> None:
    odbc = FakeOdbc(connect_errors=[hy024(database)], columns=EXPECTED_COLUMNS[:7])

    code, capture = check_odbc(tmp_path, database, odbc)

    assert code == ExitCode.ODBC_UNAVAILABLE
    assert capture.named("run_error")[0]["missing_columns"] == ["AvgOfCombined_BD"]


def test_check_odbc_fallback_failure_is_logged_without_the_path(
    tmp_path: Path, database: Path
) -> None:
    odbc = FakeOdbc(
        connect_errors=[hy024(database), FakeOdbcError("HY000", f"Could not use '{database}'")]
    )

    code, capture = check_odbc(tmp_path, database, odbc)

    assert code == ExitCode.ODBC_UNAVAILABLE
    (error,) = capture.named("run_error")
    assert error["reason"] == "connection_failed"
    assert (error["sqlstate"], error["access_mode_sqlstate"]) == ("HY000", "HY024")
    assert str(database.parent) not in capture.text
    assert str(database.parent).replace("\\", "\\\\") not in capture.text


def test_only_select_statements_are_executed(database: Path) -> None:
    odbc = FakeOdbc(rows=[source_row()])
    repo = repository(database, odbc)

    repo.probe()
    repo.extract(WINDOW)

    assert all(sql.startswith("SELECT ") for sql, _ in odbc.executed)


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM [x]", "UPDATE [x] SET a = 1", "SELECT 1; DROP TABLE [x]", "select 1"],
)
def test_non_select_statements_are_refused(sql: str) -> None:
    with pytest.raises(RuntimeError):
        _require_select(sql)


def test_source_contains_no_modifying_sql() -> None:
    package = Path(odbc_module.__file__).parent
    modifying = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE|EXEC)\b"
        r"|\.commit\(|\.rollback\("
    )

    offenders = [
        f"{path.name}:{number}"
        for path in package.glob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if modifying.search(line) and "_require_select" not in line
    ]

    assert offenders == []


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
