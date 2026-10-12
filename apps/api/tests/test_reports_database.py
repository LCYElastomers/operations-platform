"""Exports against the database: the file matches the screen's period and filters,
registers contain every matching row, and each export is audited without data.

Every CAR and cost record here is a fixture dated 2003 and is rolled back.
"""

import contextlib
import datetime as dt
import io
import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from postgres_support import requires_postgres
from principals import TESTER, TESTER_ID, TESTER_NAME, as_user
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth.models import User
from app.core.authorization import get_user_principal
from app.core.permissions import Permission as P
from app.main import create_app
from app.quality.car import service
from app.quality.car.repository import CarRepository
from app.quality.car.schemas import CarCreate
from app.quality.cost.models import CostRecord
from app.quality.cost.records import Actor
from app.reports import router as report_router

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 9, 17, 0, tzinfo=dt.UTC)
ACTOR = Actor(TESTER, NOW, user_id=TESTER_ID, name=TESTER_NAME)
OTHER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
HEADERS = {"X-Requested-With": "operations-platform"}
YEAR_2003 = {"mode": "year", "year": 2003}
CAR_EXPORT = (P.CAR_VIEW, P.QUALITY_DASHBOARD_VIEW, P.CAR_EXPORT)
COST_EXPORT = (P.QUALITY_COST_VIEW, P.QUALITY_DASHBOARD_VIEW, P.QUALITY_COST_EXPORT)
SAFETY_EXPORT = (
    P.SAFETY_RECORD_VIEW,
    P.SAFETY_DASHBOARD_VIEW,
    P.SAFETY_RECORD_EXPORT,
    P.SAFETY_OBSERVATION_VIEW,
    P.SAFETY_OBSERVATION_EXPORT,
)


class NonCommitting(CarRepository):
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
def repo(session: Session) -> NonCommitting:
    for user_id, name in ((TESTER_ID, TESTER_NAME), (OTHER_ID, "Other User (fixture)")):
        session.execute(
            insert(User).values(
                id=user_id,
                email=f"{user_id.hex}@fixture.test",
                name=name,
                status="active",
                created_by="fixture",
                updated_by="fixture",
            )
        )
    return NonCommitting(session)


@pytest.fixture
def api(session: Session, repo: NonCommitting) -> Any:
    def make(*permissions: P) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_user_principal] = lambda: as_user(*permissions)
        app.dependency_overrides[report_router.report_sessions] = lambda: (
            lambda: contextlib.nullcontext(session)
        )
        return TestClient(app)

    return make


def _car(repo: CarRepository, **fields: Any) -> Any:
    body = {"subject": "Fixture: export", "requestDate": "2003-03-04", **fields}
    return service.create(repo, CarCreate.model_validate(body), ACTOR)


def _export(client: TestClient, key: str, body: dict[str, Any]) -> Any:
    return client.post(f"/api/v1/reports/{key}/export", json=body, headers=HEADERS)


def _sheet_rows(content: bytes, sheet: str) -> list[tuple[Any, ...]]:
    workbook = load_workbook(io.BytesIO(content))
    return [row for row in workbook[sheet].iter_rows(min_row=6, values_only=True) if any(row)]


def _audits(session: Session) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == "core.report_export")
            .order_by(AuditEvent.id)
        )
    )


def test_car_register_excel_has_every_matching_row_in_order(
    api: Any, repo: NonCommitting, session: Session
) -> None:
    for day in range(1, 31):
        _car(repo, requestDate=f"2003-04-{day:02d}", departmentCode="operations")
    _car(repo, requestDate="2003-05-01", departmentCode="quality")
    _car(repo, requestDate="2004-01-01", departmentCode="operations")
    response = _export(
        api(*CAR_EXPORT),
        "car-register",
        {
            "format": "xlsx",
            "period": YEAR_2003,
            "filters": {"department": ["operations"], "sort": "oldest"},
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"] == (
        'attachment; filename="Operations-Platform_CAR-Register_2003.xlsx"'
    )
    rows = _sheet_rows(response.content, "CAR Register")
    assert len(rows) == 30
    dates = [row[1] for row in rows]
    assert dates == sorted(dates)
    assert isinstance(dates[0], dt.datetime) and dates[0].date() == dt.date(2003, 4, 1)
    assert {row[3] for row in rows} == {"Operations"}

    workbook = load_workbook(io.BytesIO(response.content))
    summary = [tuple(r) for r in workbook["Summary"].iter_rows(values_only=True)]
    assert ("Generated By", TESTER_NAME) in [r[:2] for r in summary]
    assert "Department: Operations" in [r[1] for r in summary]
    assert ("Period", "2003") in [r[:2] for r in summary]

    [event] = _audits(session)
    assert event.action == "create"
    assert event.actor_user_id == TESTER_ID
    assert event.entity_key == "car-register:xlsx"
    assert event.new_value is not None
    assert event.new_value["event"] == "REPORT_EXPORTED"
    assert event.new_value["reportKey"] == "car-register"
    assert event.new_value["format"] == "xlsx"
    assert event.new_value["period"] == "2003"
    assert "Department: Operations" in event.new_value["filters"]
    # Metadata only: no CAR data in the audit event.
    assert "Fixture: export" not in str(event.new_value)


def test_car_register_mine_uses_the_signed_in_user(api: Any, repo: NonCommitting) -> None:
    _car(repo, assignedToUserId=str(TESTER_ID), subject="Fixture: mine")
    _car(repo, assignedToUserId=str(OTHER_ID), subject="Fixture: theirs")
    response = _export(
        api(*CAR_EXPORT),
        "car-register",
        {"format": "xlsx", "period": YEAR_2003, "filters": {"mine": True}},
    )
    assert response.status_code == 200
    assert [row[2] for row in _sheet_rows(response.content, "CAR Register")] == ["Fixture: mine"]


def test_car_list_mine_sort_and_due_soon(api: Any, repo: NonCommitting) -> None:
    from app.quality.car import router as car_router

    _car(repo, requestDate="2003-01-05", assignedToUserId=str(TESTER_ID))
    _car(repo, requestDate="2003-02-05", assignedToUserId=str(OTHER_ID))
    app = create_app()
    app.dependency_overrides[car_router.car_repository] = lambda: repo
    app.dependency_overrides[get_user_principal] = lambda: as_user(P.CAR_VIEW)
    client = TestClient(app)
    base = "/api/v1/quality/cars?from=2003-01-01&to=2003-12-31"
    newest = client.get(base).json()["cars"]
    oldest = client.get(f"{base}&sort=oldest").json()["cars"]
    assert [c["requestDate"] for c in newest] == ["2003-02-05", "2003-01-05"]
    assert [c["requestDate"] for c in oldest] == ["2003-01-05", "2003-02-05"]
    mine = client.get(f"{base}&mine=true").json()
    assert mine["total"] == 1 and mine["cars"][0]["assignedToUserId"] == str(TESTER_ID)
    page = client.get(f"{base}&limit=1&offset=1").json()
    assert page["total"] == 2 and [c["requestDate"] for c in page["cars"]] == ["2003-01-05"]
    assert client.get(f"{base}&sort=sideways").status_code == 422


def test_car_dashboard_pdf_and_excel(api: Any, repo: NonCommitting, session: Session) -> None:
    _car(repo, requestDate="2003-08-04", dueDate="2003-08-20", departmentCode="operations")
    _car(repo, requestDate="2003-09-04", departmentCode="quality")
    client = api(*CAR_EXPORT)
    period = {"mode": "month", "year": 2003, "month": 8}
    pdf = _export(client, "car-dashboard", {"format": "pdf", "period": period})
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-disposition"].endswith(
        'filename="Operations-Platform_CAR-Dashboard_2003-08.pdf"'
    )
    excel = _export(client, "car-dashboard", {"format": "xlsx", "period": period})
    assert excel.status_code == 200
    workbook = load_workbook(io.BytesIO(excel.content))
    assert workbook.sheetnames == ["Summary", "Past Due", "Repeat CARs", "CARs", "Analysis"]
    cars = [r for r in workbook["CARs"].iter_rows(min_row=6, values_only=True) if any(r)]
    assert len(cars) == 1 and cars[0][1].date() == dt.date(2003, 8, 4)
    past_due = [r for r in workbook["Past Due"].iter_rows(min_row=6, values_only=True) if r[0]]
    assert len(past_due) == 1
    assert [e.new_value["format"] for e in _audits(session) if e.new_value] == ["pdf", "xlsx"]


def test_cost_reports(api: Any, repo: NonCommitting, session: Session) -> None:
    area = session.scalar(text("SELECT id FROM safety.areas WHERE active ORDER BY id LIMIT 1"))

    def record(**values: Any) -> None:
        defaults: dict[str, Any] = {
            "area_id": area,
            "record_date": dt.date(2003, 5, 1),
            "title": "Fixture",
            "coq_class": "internal_failure",
            "category_code": "internal_failure.scrap",
            "description": "Fixture record",
            "financial_status": "confirmed",
            "status": "open",
            "material_cost": 100,
            "created_by": "t",
            "updated_by": "t",
        }
        session.execute(insert(CostRecord).values(**{**defaults, **values}))

    record()
    record(record_date=dt.date(2003, 6, 1), product="FIXTURE-A", material_cost=250)
    record(
        record_date=dt.date(2003, 6, 2),
        coq_class="appraisal",
        category_code="appraisal.testing",
        material_cost=None,
    )
    client = api(*COST_EXPORT)
    for key in ("copq", "coq-matrix"):
        for fmt in ("pdf", "xlsx"):
            response = _export(client, key, {"format": fmt, "period": YEAR_2003})
            assert response.status_code == 200, (key, fmt, response.text)
    copq = _export(
        client,
        "copq",
        {
            "format": "xlsx",
            "period": {"mode": "month", "year": 2003, "month": 6},
            "filters": {"product": "FIXTURE-A"},
        },
    )
    assert copq.headers["content-disposition"].endswith('_COPQ_2003-06.xlsx"')
    summary = load_workbook(io.BytesIO(copq.content))["Summary"]
    values = {r[0]: r[1] for r in summary.iter_rows(values_only=True) if r[0]}
    assert values["Confirmed COPQ"] == 250
    assert values["Period"] == "June 2003"

    register = _export(client, "quality-cost-register", {"format": "xlsx", "period": YEAR_2003})
    rows = _sheet_rows(register.content, "Quality Cost Register")
    assert len(rows) == 3
    no_cost = [row for row in rows if row[4] == "Appraisal"]
    assert no_cost[0][11] is None  # no cost entered stays empty, not $0
    assert _export(client, "quality-cost-register", {"format": "pdf"}).status_code == 422


@pytest.mark.parametrize(
    "key", ["safety-incidents", "safety-performance", "safety-trir", "safety-observations"]
)
@pytest.mark.parametrize("fmt", ["pdf", "xlsx"])
def test_safety_reports(api: Any, session: Session, key: str, fmt: str) -> None:
    response = _export(
        api(*SAFETY_EXPORT), key, {"format": fmt, "period": {"mode": "year", "year": 2025}}
    )
    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    assert re.search(rf'filename="Operations-Platform_[A-Za-z-]+_2025(-YTD)?\.{fmt}"', disposition)
    if fmt == "pdf":
        assert response.content.startswith(b"%PDF")
    else:
        workbook = load_workbook(io.BytesIO(response.content))
        assert workbook.sheetnames[0] == "Summary"
        assert len(workbook.sheetnames) > 1
    assert len(_audits(session)) == 1


def test_unauthorized_direct_request_reads_nothing(api: Any, session: Session) -> None:
    response = _export(api(P.CAR_VIEW), "car-register", {"format": "xlsx"})
    assert response.status_code == 403
    assert _audits(session) == []
