"""PostgreSQL tests for Cost of Quality (migrations 0010 and 0011).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back. Fixture rows use 2003, so stored data is never
read or changed; the reviewed 2026 mapping is applied only to empty tables.
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
from app.quality.cost import legacy_import, records, service
from app.quality.cost.models import CostMonthlyFact, CostRecord
from app.quality.cost.repository import CostRepository, RecordFilter
from app.quality.cost.schemas import CostRecordCreate, CostRecordUpdate

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 8, 17, 0, tzinfo=dt.UTC)
TODAY = dt.date(2026, 10, 8)
API_ROOT = Path(__file__).resolve().parents[1]
MAPPING = API_ROOT / "import_templates" / "quality_cost_of_quality_2026.mapping.json"
YEAR_2003 = RecordFilter(date_from=dt.date(2003, 1, 1), date_to=dt.date(2003, 12, 31))


def migration(revision: str) -> ModuleType:
    path = next((API_ROOT / "alembic" / "versions").glob(f"*-{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", path)
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


@pytest.fixture
def area_id(session: Session) -> int:
    found = session.scalar(text("SELECT id FROM safety.areas WHERE active ORDER BY id LIMIT 1"))
    assert found is not None
    return found


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "reporting_year": 2003,
        "reporting_month": 1,
        "source": "fixture",
        "created_by": "t",
        "updated_by": "t",
        **overrides,
    }


def _record_row(area: int | None, **overrides: Any) -> dict[str, Any]:
    return {
        "record_date": dt.date(2003, 5, 1),
        "title": "Fixture",
        "area_id": area,
        "coq_class": "internal_failure",
        "category_code": "internal_failure.scrap",
        "description": "Fixture record",
        "financial_status": "confirmed",
        "status": "open",
        "created_by": "t",
        "updated_by": "t",
        **overrides,
    }


# Monthly inputs (0010) -----------------------------------------------------------


def test_facts_table_and_constraints(engine: Engine) -> None:
    inspector = inspect(engine)
    checks = {c["name"] for c in inspector.get_check_constraints("cost_monthly_facts", "quality")}

    assert {
        "ck_cost_monthly_facts_reporting_year",
        "ck_cost_monthly_facts_reporting_month",
        "ck_cost_monthly_facts_complaint_count",
        "ck_cost_monthly_facts_sales_revenue",
        "ck_cost_monthly_facts_source",
    } <= checks


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
def test_database_rejects_invalid_facts(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(CostMonthlyFact).values(_row(**overrides)))


def test_database_rejects_a_duplicate_month(session: Session) -> None:
    session.execute(insert(CostMonthlyFact).values(_row()))
    with pytest.raises(IntegrityError, match="uq_cost_monthly_facts_reporting_year"):
        session.execute(insert(CostMonthlyFact).values(_row()))


@pytest.mark.empty_database
def test_facts_downgrade_guard_refuses_while_figures_exist(session: Session) -> None:
    session.execute(insert(CostMonthlyFact).values(_row()))
    with pytest.raises(DBAPIError, match="Cost of Quality figures exist"), session.begin_nested():
        session.execute(text(migration("0010").DOWNGRADE_GUARD))


# Records (0011) ------------------------------------------------------------------


def test_records_table_and_constraints(engine: Engine) -> None:
    inspector = inspect(engine)
    checks = {c["name"] for c in inspector.get_check_constraints("cost_records", "quality")}
    columns = {c["name"]: c for c in inspector.get_columns("cost_records", "quality")}

    assert {
        "ck_cost_records_coq_class",
        "ck_cost_records_category_code",
        "ck_cost_records_closed_has_date",
        "ck_cost_records_area_required",
        "ck_cost_records_material_cost",
    } <= checks
    assert columns["material_cost"]["nullable"] is True
    assert not any(name in columns for name in ("total_cost", "net_cost", "days_open"))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"category_code": "external_failure.credit"}, "ck_cost_records_category_code"),
        ({"coq_class": "good", "category_code": "good.other"}, "ck_cost_records_coq_class"),
        ({"status": "closed"}, "ck_cost_records_closed_has_date"),
        ({"date_closed": dt.date(2003, 5, 2)}, "ck_cost_records_closed_has_date"),
        (
            {"status": "closed", "date_closed": dt.date(2003, 4, 1)},
            "ck_cost_records_date_closed_after_date",
        ),
        ({"material_cost": Decimal("-0.01")}, "ck_cost_records_material_cost"),
        ({"title": " "}, "ck_cost_records_title"),
        ({"owner": ""}, "ck_cost_records_owner"),
        ({"financial_status": "estimated"}, "ck_cost_records_financial_status"),
    ],
)
def test_database_rejects_invalid_records(
    session: Session, area_id: int, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(CostRecord).values(_record_row(area_id, **overrides)))


def test_only_imported_records_may_have_no_area(session: Session) -> None:
    session.execute(insert(CostRecord).values(_record_row(None, source="legacy_import")))
    with pytest.raises(IntegrityError, match="ck_cost_records_area_required"):
        session.execute(insert(CostRecord).values(_record_row(None)))


def test_source_keys_are_unique(session: Session) -> None:
    row = _record_row(None, source="legacy_import", source_key="fixture/2003-05/scrap")
    session.execute(insert(CostRecord).values(row))
    with pytest.raises(IntegrityError, match="uq_cost_records_source_key"):
        session.execute(insert(CostRecord).values(row))


@pytest.mark.empty_database
def test_records_downgrade_guard_refuses_while_records_exist(
    session: Session, area_id: int
) -> None:
    session.execute(insert(CostRecord).values(_record_row(area_id)))
    with pytest.raises(DBAPIError, match="Quality Cost records exist"), session.begin_nested():
        session.execute(text(migration("0011").DOWNGRADE_GUARD))


def _create(area_id: int, **overrides: Any) -> CostRecordCreate:
    data: dict[str, Any] = {
        "recordDate": "2003-05-02",
        "title": "Fixture rework",
        "areaId": area_id,
        "coqClass": "internal_failure",
        "categoryCode": "internal_failure.rework",
        "description": "Fixture: rework after a colour failure.",
        "laborCost": "1200.50",
        "materialCost": "0",
        "financialStatus": "potential",
        "status": "open",
        "product": "3411",
        "owner": "Fixture Owner",
        "references": [{"type": "reference", "key": "QN-FIXTURE"}],
        **overrides,
    }
    return CostRecordCreate.model_validate(data)


def _actor() -> records.Actor:
    return records.Actor("db-cost-tester", NOW)


def test_create_stores_null_and_zero_apart_and_audits(session: Session, area_id: int) -> None:
    repository = NonCommittingCost(session)

    row = records.create(repository, _create(area_id), _actor())

    stored = row.record
    assert stored.material_cost == 0 and stored.freight_cost is None
    assert stored.labor_cost == Decimal("1200.50")
    assert stored.created_by == stored.updated_by == "db-cost-tester"
    assert [(r.type, r.key) for r in row.references] == [("reference", "QN-FIXTURE")]
    assert row.area_name is not None
    out = records.record_out(row, TODAY)
    assert out.total_cost == Decimal("1200.50") and out.cost_confirmed is False
    event = session.scalars(
        select(AuditEvent).where(AuditEvent.entity_key == records.entity_key(stored.id))
    ).one()
    assert event.action == "create" and event.actor_id == "db-cost-tester"
    assert event.new_value["material_cost"] == "0"
    assert event.new_value["references"] == [
        {"type": "reference", "key": "QN-FIXTURE", "label": None}
    ]


def test_update_audits_old_and_new_values_and_refuses_stale_versions(
    session: Session, area_id: int
) -> None:
    repository = NonCommittingCost(session)
    created = records.create(repository, _create(area_id), _actor()).record
    record_id = created.id
    change = CostRecordUpdate.model_validate(
        {
            **_create(area_id).model_dump(by_alias=True, mode="json"),
            "version": 1,
            "financialStatus": "confirmed",
            "status": "closed",
            "dateClosed": "2003-05-20",
            "recoveredCost": "200",
            "references": [],
        }
    )

    updated = records.update(repository, record_id, change, _actor()).record

    assert updated.version == 2 and updated.status == "closed"
    assert records.record_out(repository.get(record_id), TODAY).net_cost == Decimal("1000.50")  # type: ignore[arg-type]
    assert repository.references_of(record_id) == ()
    with pytest.raises(records.RecordConflictError):
        records.update(repository, record_id, change, _actor())
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_key == records.entity_key(record_id))
        .order_by(AuditEvent.id)
    ).all()
    assert [e.action for e in events] == ["create", "update"]
    assert events[1].old_value["financial_status"] == "potential"
    assert events[1].new_value["financial_status"] == "confirmed"
    assert events[1].new_value["references"] == []


def test_filters_and_search(session: Session, area_id: int) -> None:
    repository = NonCommittingCost(session)
    first = records.create(repository, _create(area_id), _actor()).record
    records.create(
        repository,
        _create(
            area_id,
            coqClass="appraisal",
            categoryCode="appraisal.calibration",
            title="Fixture calibration",
            product=None,
            owner="Someone Else",
            financialStatus="confirmed",
        ),
        _actor(),
    )

    def ids(**criteria: Any) -> list[int]:
        rows, _ = repository.search(
            RecordFilter(date_from=dt.date(2003, 1, 1), date_to=dt.date(2003, 12, 31), **criteria)
        )
        return [r.record.id for r in rows]

    assert len(ids()) == 2
    assert ids(product="3411") == [first.id]
    assert ids(owner="fixture owner") == [first.id]
    assert ids(coq_classes=("internal_failure", "external_failure")) == [first.id]
    assert ids(financial_statuses=("potential",)) == [first.id]
    assert ids(search="fixture REWORK") == [first.id]
    assert ids(search="100%_") == []
    assert ids(search="none", search_id=first.id) == [first.id]
    assert "3411" in repository.distinct_values("product")


def test_import_applies_months_and_records_audits_and_is_idempotent(
    session: Session, tmp_path: Path
) -> None:
    data = json.loads(MAPPING.read_text(encoding="utf-8"))
    for index, entry in enumerate(data["months"]):
        entry["year"] = 2003
        entry["month"] = index + 1
    path = tmp_path / "fixture.mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    mapping = legacy_import.load_mapping(path)
    repository = NonCommittingCost(session)

    months, record_count, change_set = legacy_import.apply_plan(
        repository, mapping, path, actor_id="db-cost-tester", now=NOW
    )
    facts = {k: v for k, v in repository.facts().items() if k[0] == 2003}
    again = legacy_import.plan_import(facts, mapping, repository.by_source_key(), today=TODAY)

    assert (months, record_count) == (2, 5) and change_set is not None
    assert again.empty and not again.blocked
    rows, _ = repository.search(YEAR_2003)
    stored = {r.record.source_key: r.record for r in rows}
    scrap = stored["coq-workbook/2003-02/scrap"]
    assert scrap.material_cost == Decimal("16851.25")
    assert scrap.source == "legacy_import" and scrap.area_id is None
    assert scrap.source_reference is not None and "Production!" in scrap.source_reference
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.change_set_id == change_set).order_by(AuditEvent.id)
    ).all()
    assert [e.entity_key for e in events][:2] == [
        "cost-monthly-facts/2003-01",
        "cost-monthly-facts/2003-02",
    ]
    assert sum(e.entity_type == records.ENTITY_TYPE for e in events) == 5
    assert legacy_import.apply_plan(repository, mapping, path, actor_id="x", now=NOW) == (
        0,
        0,
        None,
    )


@pytest.mark.empty_database
def test_reviewed_mapping_applies_to_empty_tables(session: Session) -> None:
    mapping = legacy_import.load_mapping(MAPPING)
    repository = NonCommittingCost(session)

    months, record_count, _ = legacy_import.apply_plan(
        repository, mapping, MAPPING, actor_id="db-cost-tester", now=NOW
    )
    rows, _ = repository.search(RecordFilter())
    stored = [service.MonthInputs.from_row(row) for row in repository.facts().values()]
    body = service.summary(
        [r.record for r in rows],
        stored,
        year=2026,
        available_years=repository.record_years(),
        from_month=None,
        through_month=None,
        today=TODAY,
    )

    assert (months, record_count) == (2, 5)
    assert body.copq.figures.confirmed == Decimal("75946.92")
    assert body.matrix.poor == Decimal("75946.92") and body.matrix.total is None
    assert (body.from_month, body.through_month) == (1, 2)
