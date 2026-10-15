"""Safety data is durable in PostgreSQL and is never only in transient storage.

Unit tests need no database. The PostgreSQL tests (TEST_DATABASE_URL) run in a
rolled-back transaction, except the ``empty_database`` test that commits through
the real import commands, reads back through a new engine, and deletes what it
committed.
"""

import datetime as dt
import hashlib
import importlib.util
import re
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from principals import as_user
from sqlalchemy import Engine, create_engine, delete, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1 import health
from app.audit.models import AuditEvent
from app.core.authorization import get_user_principal
from app.core.permissions import Permission
from app.db.schema_state import SchemaState
from app.main import create_app
from app.safety import legacy_import as metrics_import
from app.safety import reconcile
from app.safety import service as metrics_service
from app.safety.imports import runs
from app.safety.imports.models import ImportRun
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.performance import legacy_import as hours_import
from app.safety.performance.models import PerformanceAnnualLegacy, PerformanceHours
from app.safety.performance.repository import DatabasePerformanceRepository
from app.safety.records.models import IncidentRecord
from app.safety.repository import DatabaseSafetyMetricsRepository
from app.safety.trir import router as trir_router

API_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = API_ROOT / "import_templates"
INCIDENTS_2026 = TEMPLATES / "safety_incidents_2026_lcy_ehs.mapping.json"
HOURS = TEMPLATES / "safety_performance_hours_lcy_ehs.mapping.json"
NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)
SHA = "0" * 64


# Static guards (no database) -----------------------------------------------------------


def _safety_sources() -> list[Path]:
    return sorted((API_ROOT / "app" / "safety").rglob("*.py"))


def test_safety_code_never_truncates_drops_or_uses_transient_tables() -> None:
    pattern = re.compile(
        r"\b(TRUNCATE\s|DROP\s+TABLE\b|CREATE\s+(TEMP|TEMPORARY|UNLOGGED|MATERIALIZED)\b|"
        r"SELECT\s.*\bINTO\s+TEMP)",
        re.IGNORECASE,
    )
    offenders = [
        f"{path.relative_to(API_ROOT)}:{n}"
        for path in _safety_sources()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


def test_safety_runtime_code_never_reads_import_templates_or_workbooks() -> None:
    """Dashboards and APIs read PostgreSQL only; reviewed files are read by the
    operator commands, which take the path as an argument."""
    runtime = [
        p
        for p in _safety_sources()
        if p.name in ("router.py", "service.py", "repository.py", "store.py")
        or p.parent.name == "safety"
        and p.name in ("analytics.py", "reports.py", "rates.py")
        or p.parent.name == "records"
        and p.name in ("insights.py", "categories.py", "details.py", "detail_models.py")
    ]
    assert {"insights.py", "categories.py", "details.py"} <= {p.name for p in runtime}
    for path in runtime:
        source = path.read_text(encoding="utf-8")
        assert "import_templates" not in source, path
        assert ".xlsx" not in source or path.name == "router.py", path


# Readiness -----------------------------------------------------------------------------


def test_ready_is_503_when_the_database_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def not_configured() -> Any:
        raise health.DatabaseNotConfiguredError

    monkeypatch.setattr(health, "get_sessionmaker", not_configured)
    response = TestClient(create_app()).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "not_configured"}


class _FakeSession:
    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def connection(self) -> None:
        return None


@pytest.mark.parametrize(
    ("current", "status_code", "body"),
    [
        (("0016",), 200, {"status": "ready", "database": "ok"}),
        (("0015",), 503, {"status": "not_ready", "database": "migrations_pending"}),
        ((), 503, {"status": "not_ready", "database": "migrations_pending"}),
    ],
)
def test_ready_reports_pending_migrations(
    monkeypatch: pytest.MonkeyPatch,
    current: tuple[str, ...],
    status_code: int,
    body: dict[str, str],
) -> None:
    monkeypatch.setattr(health, "get_sessionmaker", lambda: _FakeSession)
    monkeypatch.setattr(health, "schema_state", lambda c: SchemaState(current, "0016"))
    response = TestClient(create_app()).get("/api/v1/health/ready")
    assert response.status_code == status_code
    assert response.json() == body
    assert "postgres" not in response.text.lower()


def test_ready_is_503_when_the_database_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(connection: Any) -> SchemaState:
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    monkeypatch.setattr(health, "get_sessionmaker", lambda: _FakeSession)
    monkeypatch.setattr(health, "schema_state", broken)
    response = TestClient(create_app()).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert "refused" not in response.text


# TRIR never turns a failed read into zero ----------------------------------------------


class _BrokenSession:
    def __getattr__(self, name: str) -> Any:
        def fail(*args: object, **kwargs: object) -> Any:
            raise OperationalError("SELECT", {}, Exception("server closed the connection"))

        return fail


@pytest.mark.parametrize("path", ["experience", "current", "history", "monthly"])
def test_trir_database_failure_is_503_not_zero(path: str) -> None:
    app = create_app()
    app.dependency_overrides[trir_router.trir_session] = _BrokenSession
    app.dependency_overrides[get_user_principal] = lambda: as_user(
        Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW
    )
    response = TestClient(app).get(f"/api/v1/safety/trir/{path}")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"
    assert "0.00" not in response.text


# Import runs: recorder (no database) ---------------------------------------------------


def test_database_error_messages_never_carry_statement_parameters() -> None:
    error = IntegrityError("INSERT ... VALUES (%(secret)s)", {"secret": "x"}, Exception("dup"))
    assert runs._describe(error) == "IntegrityError: database error"
    assert runs._describe(ValueError("bad row")) == "ValueError: bad row"


def test_messages_are_bounded() -> None:
    kept = runs._messages(["x" * 5000] * 500)
    assert len(kept) == runs.MAX_MESSAGES
    assert {len(m) for m in kept} == {runs.MAX_MESSAGE_LENGTH}


# PostgreSQL -----------------------------------------------------------------------------


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        yield db
        db.close()
        transaction.rollback()


def _sessions(session: Session) -> Any:
    """Separate sessions on the test connection; their commits release savepoints."""
    return lambda: Session(bind=session.connection(), join_transaction_mode="create_savepoint")


def _track(session: Session, **overrides: Any) -> Any:
    return runs.track(
        _sessions(session),
        importer=overrides.pop("importer", "monthly_metrics"),
        command=overrides.pop("command", "plan"),
        source_file_name="fixture.mapping.json",
        source_sha256=SHA,
        initiated_by="operator:fixture",
        clock=lambda: NOW,
        **overrides,
    )


def _run(session: Session, run_id: uuid.UUID) -> ImportRun:
    session.expire_all()
    return session.scalars(select(ImportRun).where(ImportRun.run_id == run_id)).one()


@requires_postgres
def test_a_run_is_recorded_before_the_import_and_its_outcome_after(session: Session) -> None:
    with _track(session) as run_:
        during = _run(session, run_.run_id)
        assert during.status == "running" and during.finished_at is None
        run_.finish("planned", inserted=3, skipped=2, conflicts=0, messages=["fixture"])
    row = _run(session, run_.run_id)
    assert (row.status, row.inserted_count, row.skipped_count, row.conflict_count) == (
        "planned",
        3,
        2,
        0,
    )
    assert row.updated_count is None and row.failed_count is None
    assert row.finished_at == NOW and row.messages == ["fixture"]
    assert row.source_sha256 == SHA and row.initiated_by == "operator:fixture"


@requires_postgres
def test_a_failed_import_is_recorded_and_the_error_raised(session: Session) -> None:
    with pytest.raises(ValueError, match="bad row"), _track(session) as run_:
        raise ValueError("bad row")
    row = _run(session, run_.run_id)
    assert row.status == "failed" and row.messages == ["ValueError: bad row"]
    assert row.change_set_id is None


@requires_postgres
def test_a_blocked_outcome_is_kept_when_the_import_then_raises(session: Session) -> None:
    with pytest.raises(RuntimeError), _track(session, command="apply") as run_:
        run_.finish("blocked", conflicts=1, messages=["CONFLICT fixture"])
        raise RuntimeError("refused")
    assert _run(session, run_.run_id).status == "blocked"


@requires_postgres
def test_an_applied_outcome_is_kept_when_a_later_step_fails(session: Session) -> None:
    change_set = uuid.uuid4()
    with pytest.raises(OSError), _track(session, command="apply") as run_:
        run_.finish("applied", inserted=1, change_set_id=change_set)
        raise OSError("console closed")
    row = _run(session, run_.run_id)
    assert row.status == "applied" and row.change_set_id == change_set
    assert row.messages == ["OSError: console closed"]


@requires_postgres
def test_a_run_without_a_result_is_recorded_as_failed(session: Session) -> None:
    with _track(session) as run_:
        pass
    assert _run(session, run_.run_id).status == "failed"


def _run_row(**overrides: Any) -> dict[str, Any]:
    return {
        "run_id": uuid.uuid4(),
        "importer": "monthly_metrics",
        "command": "apply",
        "source_file_name": "fixture.json",
        "source_sha256": SHA,
        "initiated_by": "operator:fixture",
        "started_at": NOW,
        "finished_at": NOW,
        "status": "applied",
        "change_set_id": uuid.uuid4(),
        **overrides,
    }


@requires_postgres
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"importer": "excel"}, "ck_import_runs_importer"),
        ({"status": "done", "change_set_id": None}, "ck_import_runs_status"),
        ({"command": "plan"}, "ck_import_runs_apply_outcome"),
        ({"status": "planned"}, "ck_import_runs_change_set"),
        ({"finished_at": None}, "ck_import_runs_finished"),
        ({"status": "running", "change_set_id": None}, "ck_import_runs_finished"),
        ({"source_sha256": "ABC"}, "ck_import_runs_source_sha256"),
        ({"source_file_name": "  "}, "ck_import_runs_source_file_name"),
        ({"inserted_count": -1}, "ck_import_runs_counts"),
    ],
)
def test_import_run_constraints(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(ImportRun).values(_run_row(**overrides)))


@requires_postgres
def test_downgrade_guard_refuses_while_import_runs_exist(session: Session) -> None:
    path = next((API_ROOT / "alembic" / "versions").glob("*-0016_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0016", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    session.execute(insert(ImportRun).values(_run_row()))
    with pytest.raises(DBAPIError, match="import runs exist"), session.begin_nested():
        session.execute(text(module.DOWNGRADE_GUARD))


# Reconciliation (rolled back) ----------------------------------------------------------


def _category(session: Session, section: str, code: str) -> int:
    return session.scalars(
        select(MetricCategory.id)
        .join(MetricSection, MetricSection.id == MetricCategory.section_id)
        .where(
            MetricSection.metric_set == "incidents",
            MetricSection.code == section,
            MetricCategory.code == code,
        )
    ).one()


def _record(session: Session, day: dt.date, **overrides: Any) -> None:
    session.execute(
        insert(IncidentRecord).values(
            event_type="incident",
            incident_date=day,
            description="ZZ durability fixture",
            created_by="t",
            updated_by="t",
            **overrides,
        )
    )


def _value(session: Session, section: str, code: str, month: int, value: int) -> None:
    session.execute(
        insert(MonthlyMetricValue).values(
            category_id=_category(session, section, code),
            reporting_year=2003,
            reporting_month=month,
            value=value,
            created_by="t",
            updated_by="t",
        )
    )


def _statuses(findings: list[reconcile.Finding], check: str) -> list[tuple[str, str]]:
    return [(f.status, f.message) for f in findings if f.check == check]


@requires_postgres
def test_reconcile_reports_a_record_the_monthly_totals_do_not_count(session: Session) -> None:
    _record(session, dt.date(2003, 8, 19), incident_number="ZZT-2003-063")
    found = _statuses(reconcile.check_totals_against_records(session, 2003), "totals_vs_records")
    assert found == [
        (
            "discrepancy",
            "Records not counted: 2003-08 incident total unreported, records 1 "
            "(total_unreported_with_records).",
        )
    ]

    _value(session, "incident_near_miss_totals", "incident", 8, 1)
    found = _statuses(reconcile.check_totals_against_records(session, 2003), "totals_vs_records")
    assert found == [("ok", "2003 totals and records agree.")]


@requires_postgres
def test_reconcile_matches_classifications_by_code_and_lists_unclassified(
    session: Session,
) -> None:
    recordable = _category(session, "incident_classification", "recordable_injury")
    _record(session, dt.date(2003, 3, 4), classification_category_id=recordable)
    _record(session, dt.date(2003, 8, 19), incident_number="ZZT-2003-063")
    findings = reconcile.check_classifications(session, 2003)
    assert (
        "discrepancy",
        "2003-03 recordable_injury: 1 records, monthly count unreported.",
    ) in _statuses(findings, "classifications")
    assert any(
        status == "warning" and "ZZT-2003-063" in message and "an owner must classify" in message
        for status, message in _statuses(findings, "classifications")
    )

    _value(session, "incident_classification", "recordable_injury", 3, 1)
    statuses = _statuses(reconcile.check_classifications(session, 2003), "classifications")
    assert not any(status == "discrepancy" for status, _ in statuses)


@requires_postgres
def test_trir_counts_match_category_codes_not_display_names(session: Session) -> None:
    _value(session, "incident_classification", "recordable_injury", 3, 1)
    _value(session, "incident_classification", "first_aid", 3, 4)
    repository = DatabasePerformanceRepository(session)
    before, _ = repository.counts([2003])
    assert before[(2003, 3)] == {"recordable_injury": 1, "first_aid": 4}

    session.execute(
        text(
            "UPDATE safety.metric_categories SET name = 'Renamed for display' "
            "WHERE code IN ('recordable_injury', 'first_aid')"
        )
    )
    after, _ = repository.counts([2003])
    assert after == before


@requires_postgres
def test_reconcile_flags_non_permanent_storage_in_safety(session: Session) -> None:
    assert reconcile.check_relations(session)[0].status == "ok"
    session.execute(text("CREATE UNLOGGED TABLE safety.zz_staging_fixture (id integer)"))
    finding = reconcile.check_relations(session)[0]
    assert finding.status == "discrepancy"
    assert "safety.zz_staging_fixture (unlogged)" in finding.message


@requires_postgres
def test_reconcile_schema_check_passes_at_head(session: Session) -> None:
    assert reconcile.check_schema(session)[0].status == "ok"


# Reviewed files -> PostgreSQL -> TRIR (disposable database only) -----------------------


@requires_postgres
@pytest.mark.empty_database
def test_reconcile_reports_reviewed_values_until_they_are_stored_and_trir_follows(
    session: Session,
) -> None:
    def stored() -> list[tuple[str, str]]:
        return [
            (f.status, f.message) for f in reconcile.check_incidents_file(session, INCIDENTS_2026)
        ]

    assert stored() == [("discrepancy", "70 values reported in the file are not stored.")]
    assert reconcile.check_trir(session, 2026)[0].status == "warning"

    class Metrics(DatabaseSafetyMetricsRepository):
        def commit(self) -> None:
            session.flush()

    class Performance(DatabasePerformanceRepository):
        def commit(self) -> None:
            session.flush()

    mapping = metrics_import.load_mapping(INCIDENTS_2026)
    metrics_service.save_changes(
        Metrics(session),
        metric_set=mapping.metric_set,
        year=mapping.year,
        changes=metrics_import.plan_import(Metrics(session), mapping).changes,
        actor_id="db-durability-tester",
        now=NOW,
    )
    hours = hours_import.load_mapping(HOURS)
    hours_import.apply_plan(
        Performance(session),
        hours_import.plan_import(Performance(session), hours, today=NOW.date()),
        now=NOW,
    )

    assert stored() == [("ok", "All 70 reported values are stored.")]
    (trir, *_) = reconcile.check_trir(session, 2026)
    assert (trir.status, trir.message) == (
        "ok",
        "2026 TRIR 1.38 (recordables 1, hours 145194.0, through month 8).",
    )


@requires_postgres
@pytest.mark.empty_database
def test_imports_commit_to_permanent_tables_and_survive_a_new_engine(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real import commands commit; a new engine (a restarted process) reads
    the same values, the import runs and TRIR back from PostgreSQL."""
    factory = sessionmaker(bind=engine)
    for module in (metrics_import, hours_import, runs):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)
    try:
        assert metrics_import.run("apply", INCIDENTS_2026) == 0
        assert hours_import.run("apply", HOURS) == 0
        assert metrics_import.run("apply", INCIDENTS_2026) == 0
        engine.dispose()

        restarted = create_engine(engine.url)
        try:
            with Session(restarted) as fresh:
                (trir, *_) = reconcile.check_trir(fresh, 2026)
                assert trir.message.startswith("2026 TRIR 1.38 (recordables 1, hours 145194.0")
                recorded = fresh.execute(
                    select(ImportRun.importer, ImportRun.command, ImportRun.status,
                           ImportRun.inserted_count, ImportRun.source_sha256,
                           ImportRun.change_set_id.is_not(None))
                    .order_by(ImportRun.id)
                ).all()  # fmt: skip
                incidents_sha = hashlib.sha256(INCIDENTS_2026.read_bytes()).hexdigest()
                hours_sha = hashlib.sha256(HOURS.read_bytes()).hexdigest()
                assert [tuple(r) for r in recorded] == [
                    ("monthly_metrics", "apply", "applied", 70, incidents_sha, True),
                    ("performance", "apply", "applied", 23, hours_sha, True),
                    ("monthly_metrics", "apply", "nothing_to_apply", 0, incidents_sha, False),
                ]
                change_sets = [
                    c for c in fresh.scalars(select(ImportRun.change_set_id)) if c is not None
                ]
                audited = fresh.scalars(
                    select(AuditEvent.change_set_id).where(
                        AuditEvent.change_set_id.in_(change_sets)
                    )
                ).all()
                assert set(audited) == set(change_sets)
        finally:
            restarted.dispose()
    finally:
        with engine.begin() as connection:
            change_sets = list(
                connection.scalars(
                    select(ImportRun.change_set_id).where(ImportRun.change_set_id.is_not(None))
                )
            )
            connection.execute(delete(AuditEvent).where(AuditEvent.change_set_id.in_(change_sets)))
            connection.execute(
                delete(MonthlyMetricValue).where(MonthlyMetricValue.reporting_year == 2026)
            )
            connection.execute(delete(PerformanceHours))
            connection.execute(delete(PerformanceAnnualLegacy))
            connection.execute(delete(ImportRun))


def test_hours_fixture_totals_are_what_the_trir_assertions_expect() -> None:
    hours = hours_import.load_mapping(HOURS)
    through_august = sum(
        (h.total_hours for h in hours.hours if h.year == 2026 and h.month <= 8), Decimal(0)
    )
    assert through_august == Decimal("145194.00")
