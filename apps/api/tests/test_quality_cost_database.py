"""PostgreSQL tests for the monthly Cost of Quality inputs (migration 0010).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back. Rows use 2003 (fixture months), so stored data
is never read or changed; the reviewed 2026 mapping is applied only to an empty
table.
"""

import datetime as dt
import importlib.util
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.quality.cost import legacy_import, service
from app.quality.cost.models import CostMonthlyFact
from app.quality.cost.repository import CostRepository

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 8, 17, 0, tzinfo=dt.UTC)
API_ROOT = Path(__file__).resolve().parents[1]
MAPPING = API_ROOT / "import_templates" / "quality_cost_of_quality_2026.mapping.json"


def migration_0010() -> ModuleType:
    path = next((API_ROOT / "alembic" / "versions").glob("*-0010_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0010", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NonCommittingCost(CostRepository):
    def commit(self) -> None:
        self.session.flush()

    def rollback(self) -> None:
        pass


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        yield db
        db.close()
        transaction.rollback()


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "reporting_year": 2003,
        "reporting_month": 1,
        "source": "fixture",
        "created_by": "t",
        "updated_by": "t",
        **overrides,
    }


def test_table_and_constraints(engine: Engine) -> None:
    inspector = inspect(engine)
    checks = {c["name"] for c in inspector.get_check_constraints("cost_monthly_facts", "quality")}

    assert {
        "ck_cost_monthly_facts_reporting_year",
        "ck_cost_monthly_facts_reporting_month",
        "ck_cost_monthly_facts_complaint_count",
        "ck_cost_monthly_facts_sales_revenue",
        "ck_cost_monthly_facts_source",
    } <= checks
    columns = {c["name"]: c for c in inspector.get_columns("cost_monthly_facts", "quality")}
    assert columns["sales_revenue"]["nullable"] is True
    assert not any(name in columns for name in ("copq", "prevention", "appraisal"))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"reporting_month": 13}, "ck_cost_monthly_facts_reporting_month"),
        ({"reporting_year": 1999}, "ck_cost_monthly_facts_reporting_year"),
        ({"scrap_produced_lbs": Decimal(-1)}, "ck_cost_monthly_facts_scrap_produced_lbs"),
        ({"complaint_count": -1}, "ck_cost_monthly_facts_complaint_count"),
        ({"source": "  "}, "ck_cost_monthly_facts_source"),
    ],
)
def test_database_rejects_invalid_rows(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(CostMonthlyFact).values(_row(**overrides)))


def test_database_rejects_a_duplicate_month(session: Session) -> None:
    session.execute(insert(CostMonthlyFact).values(_row()))
    with pytest.raises(IntegrityError, match="uq_cost_monthly_facts_reporting_year"):
        session.execute(insert(CostMonthlyFact).values(_row()))


def test_null_and_zero_round_trip_separately(session: Session) -> None:
    session.execute(
        insert(CostMonthlyFact).values(
            _row(outbound_freight=Decimal(0), return_freight=None, sales_revenue=Decimal("5"))
        )
    )
    row = CostRepository(session).facts()[(2003, 1)]
    cost = service.month_cost(service.MonthInputs.from_row(row))

    assert row.outbound_freight == 0 and row.return_freight is None
    assert cost.elements["outbound_freight"] == 0 and cost.elements["return_freight"] is None


@pytest.mark.empty_database
def test_downgrade_guard_refuses_while_figures_exist(session: Session) -> None:
    session.execute(insert(CostMonthlyFact).values(_row()))
    with pytest.raises(DBAPIError, match="Cost of Quality figures exist"), session.begin_nested():
        session.execute(text(migration_0010().DOWNGRADE_GUARD))


def test_import_applies_audits_and_is_idempotent(session: Session, tmp_path: Path) -> None:
    data = json.loads(MAPPING.read_text(encoding="utf-8"))
    for index, entry in enumerate(data["months"]):
        entry["year"] = 2003
        entry["month"] = index + 1
    path = tmp_path / "fixture.mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    mapping = legacy_import.load_mapping(path)
    repository = NonCommittingCost(session)

    count, change_set = legacy_import.apply_plan(
        repository, mapping, path, actor_id="db-cost-tester", now=NOW
    )
    facts = {k: v for k, v in repository.facts().items() if k[0] == 2003}
    again = legacy_import.plan_import(facts, mapping)

    assert count == 2 and change_set is not None
    assert (again.inserts, again.differing, again.unchanged) == ([], [], [(2003, 1), (2003, 2)])
    january = facts[(2003, 1)]
    assert january.offspec_produced_lbs is None
    assert january.sales_revenue == Decimal("10259998")
    assert january.source_reference is not None and "Production!D3" in january.source_reference
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.change_set_id == change_set).order_by(AuditEvent.id)
    ).all()
    assert [e.entity_key for e in events] == [
        "cost-monthly-facts/2003-01",
        "cost-monthly-facts/2003-02",
    ]
    assert legacy_import.apply_plan(repository, mapping, path, actor_id="x", now=NOW) == (0, None)


@pytest.mark.empty_database
def test_reviewed_mapping_applies_to_an_empty_table(session: Session) -> None:
    mapping = legacy_import.load_mapping(MAPPING)
    repository = NonCommittingCost(session)

    count, _ = legacy_import.apply_plan(
        repository, mapping, MAPPING, actor_id="db-cost-tester", now=NOW
    )
    stored = [service.MonthInputs.from_row(row) for row in repository.facts().values()]
    body = service.summary(stored, year=2026, from_month=None, through_month=None)

    assert count == 2
    assert body.period.copq == Decimal("75946.92")
    assert body.matrix.total is None
