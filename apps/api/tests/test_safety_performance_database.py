"""PostgreSQL integration tests for Safety Performance (migration 0006).

Enabled by TEST_DATABASE_URL (see test_moisture_database.py). Each test runs in
a transaction that is rolled back. Rows use the years 2003 and 2098-2099, and
audit queries filter on the test actor, so other rows are never read.
"""

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.performance import service
from app.safety.performance.calculations import INCIDENT_CATEGORIES, LEGACY_CATEGORIES
from app.safety.performance.models import PerformanceAnnualLegacy, PerformanceHours
from app.safety.performance.repository import DatabasePerformanceRepository, HoursValues
from app.safety.performance.schemas import SaveMonthHoursRequest
from app.safety.performance.service import EditConflictError

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
ACTOR = "db-tester"


class NonCommittingRepository(DatabasePerformanceRepository):
    """Flushes instead of committing, so the test transaction can be rolled back."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.session = session

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
def repository(session: Session) -> NonCommittingRepository:
    return NonCommittingRepository(session)


def hours_row(**overrides: Any) -> dict[str, Any]:
    return {
        "reporting_year": 2003,
        "reporting_month": 1,
        "total_hours": Decimal("1000.00"),
        "created_by": ACTOR,
        "updated_by": ACTOR,
        **overrides,
    }


def annual_row(**overrides: Any) -> dict[str, Any]:
    return {
        "reporting_year": 2003,
        "recordables": 1,
        "total_hours": Decimal("1000.00"),
        "source": "test",
        "created_by": ACTOR,
        "updated_by": ACTOR,
        **overrides,
    }


def category_id(session: Session, metric_set: str, section: str, category: str) -> int:
    return session.scalars(
        select(MetricCategory.id)
        .join(MetricSection, MetricSection.id == MetricCategory.section_id)
        .where(
            MetricSection.metric_set == metric_set,
            MetricSection.code == section,
            MetricCategory.code == category,
        )
    ).one()


def store_value(
    session: Session, metric_set: str, key: tuple[str, str], year: int, month: int, value: int
) -> None:
    session.execute(
        insert(MonthlyMetricValue).values(
            category_id=category_id(session, metric_set, *key),
            reporting_year=year,
            reporting_month=month,
            value=value,
            created_by=ACTOR,
            updated_by=ACTOR,
        )
    )


# Schema --------------------------------------------------------------------------


def test_tables_columns_and_constraints(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("performance_hours", schema="safety")}

    assert set(columns) == {
        "id",
        "reporting_year",
        "reporting_month",
        "total_hours",
        "hourly_hours",
        "salary_hours",
        "month_closed",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    }
    assert columns["total_hours"]["nullable"] is False
    assert columns["hourly_hours"]["nullable"] is True
    assert str(columns["total_hours"]["type"]) == "NUMERIC(10, 2)"
    assert columns["month_closed"]["default"] == "false"
    checks = {c["name"] for c in inspector.get_check_constraints("performance_hours", "safety")}
    assert checks == {
        "ck_performance_hours_reporting_year",
        "ck_performance_hours_reporting_month",
        "ck_performance_hours_total_hours",
        "ck_performance_hours_hourly_hours",
        "ck_performance_hours_salary_hours",
        "ck_performance_hours_breakdown_total",
    }
    uniques = inspector.get_unique_constraints("performance_hours", schema="safety")
    assert [(u["name"], u["column_names"]) for u in uniques] == [
        ("uq_performance_hours_year_month", ["reporting_year", "reporting_month"])
    ]
    annual = {c["name"] for c in inspector.get_columns("performance_annual_legacy", "safety")}
    assert {"reporting_year", "recordables", "total_hours", "source"} <= annual


def test_numerator_categories_exist(session: Session) -> None:
    for key in INCIDENT_CATEGORIES.values():
        assert category_id(session, "incidents", *key)
    for key in LEGACY_CATEGORIES.values():
        assert category_id(session, "performance_legacy", *key)


@pytest.mark.parametrize(
    ("table", "row"),
    [
        (PerformanceHours, hours_row(total_hours=Decimal("-0.01"))),
        (PerformanceHours, hours_row(hourly_hours=Decimal("-1"))),
        (PerformanceHours, hours_row(salary_hours=Decimal("-1"))),
        (
            PerformanceHours,
            hours_row(hourly_hours=Decimal("600"), salary_hours=Decimal("300")),
        ),
        (PerformanceHours, hours_row(reporting_month=13)),
        (PerformanceHours, hours_row(reporting_year=1999)),
        (PerformanceHours, hours_row(total_hours=None)),
        (PerformanceAnnualLegacy, annual_row(total_hours=Decimal("0"))),
        (PerformanceAnnualLegacy, annual_row(recordables=-1)),
        (PerformanceAnnualLegacy, annual_row(source=" padded ")),
        (PerformanceAnnualLegacy, annual_row(source="")),
    ],
)
def test_constraints_reject_invalid_rows(
    session: Session, table: type[Any], row: dict[str, Any]
) -> None:
    with pytest.raises(IntegrityError):
        session.execute(insert(table).values(**row))
        session.flush()


def test_breakdown_may_be_partial_and_month_closed_defaults_false(session: Session) -> None:
    session.execute(insert(PerformanceHours).values(**hours_row(hourly_hours=Decimal("400"))))
    session.execute(
        insert(PerformanceHours).values(
            **hours_row(
                reporting_month=2,
                hourly_hours=Decimal("600.50"),
                salary_hours=Decimal("399.50"),
            )
        )
    )

    rows = session.scalars(
        select(PerformanceHours).where(PerformanceHours.reporting_year == 2003)
    ).all()
    assert [r.month_closed for r in rows] == [False, False]


def test_one_row_per_month_and_per_annual_year(session: Session) -> None:
    session.execute(insert(PerformanceHours).values(**hours_row()))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(insert(PerformanceHours).values(**hours_row()))
    session.execute(insert(PerformanceAnnualLegacy).values(**annual_row()))
    with pytest.raises(IntegrityError):
        session.execute(insert(PerformanceAnnualLegacy).values(**annual_row()))


# Service ---------------------------------------------------------------------------


def request(**overrides: Any) -> SaveMonthHoursRequest:
    data = {"totalHours": 1000, "monthClosed": True, "expectedUpdatedAt": None, **overrides}
    return SaveMonthHoursRequest.model_validate(data)


def audit_events(session: Session) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == "safety.performance_hours")
            .where(AuditEvent.actor_id == ACTOR)
            .order_by(AuditEvent.id)
        )
    )


def test_save_update_clear_round_trip_with_audit(
    session: Session, repository: NonCommittingRepository
) -> None:
    created = service.save_month(
        repository,
        2003,
        5,
        request(totalHours=1000.5, hourlyHours=600.25, salaryHours=400.25),
        actor_id=ACTOR,
        now=NOW,
    )
    assert created.values == HoursValues(
        Decimal("1000.50"), Decimal("600.25"), Decimal("400.25"), True
    )

    later = NOW + dt.timedelta(minutes=5)
    updated = service.save_month(
        repository,
        2003,
        5,
        request(totalHours=900, monthClosed=False, expectedUpdatedAt=created.updated_at),
        actor_id=ACTOR,
        now=later,
    )
    assert updated.values == HoursValues(Decimal("900.00"), None, None, False)
    assert updated.updated_at == later

    with pytest.raises(EditConflictError):
        service.save_month(
            repository,
            2003,
            5,
            request(expectedUpdatedAt=created.updated_at),
            actor_id=ACTOR,
            now=later,
        )

    service.clear_month(repository, 2003, 5, expected_updated_at=later, actor_id=ACTOR, now=later)
    assert repository.get_hours(2003, 5) is None

    events = audit_events(session)
    assert [(e.action, e.entity_key) for e in events] == [
        ("create", "performance-hours/2003-05"),
        ("update", "performance-hours/2003-05"),
        ("delete", "performance-hours/2003-05"),
    ]
    assert events[0].new_value == {
        "total_hours": "1000.50",
        "hourly_hours": "600.25",
        "salary_hours": "400.25",
        "month_closed": True,
    }
    assert events[1].old_value is not None and events[1].old_value["month_closed"] is True
    assert events[1].new_value is not None and events[1].new_value["month_closed"] is False
    assert events[2].new_value is None


def close_months(repository: NonCommittingRepository, year: int, months: range, hours: int) -> None:
    for month in months:
        repository.insert_hours(
            year, month, HoursValues(Decimal(hours), None, None, True), actor_id=ACTOR, at=NOW
        )


def test_rates_read_stored_incident_counts(
    session: Session, repository: NonCommittingRepository
) -> None:
    close_months(repository, 2098, range(1, 13), 1000)
    close_months(repository, 2099, range(1, 3), 2000)
    repository.insert_hours(
        2099, 3, HoursValues(Decimal(2000), None, None, False), actor_id=ACTOR, at=NOW
    )
    incident = INCIDENT_CATEGORIES
    store_value(session, "incidents", incident["recordable_injury"], 2098, 6, 2)
    store_value(session, "incidents", incident["recordable_injury"], 2099, 1, 1)
    store_value(session, "incidents", incident["occupational_illness"], 2099, 2, 1)
    store_value(session, "incidents", incident["property_damage"], 2099, 2, 2)
    store_value(session, "incidents", incident["equipment_damage_failure"], 2099, 2, 1)
    store_value(session, "incidents", incident["lopc"], 2099, 3, 5)  # open month
    session.flush()

    data = service.dashboard(repository, 2099, through_month=None, now=NOW)

    assert data.count_source == "incidents"
    assert data.through_month == 2
    rates = {k.measure: k for k in data.kpis}
    assert (rates["trir"].ytd.events, rates["trir"].ytd.hours) == (2, 4000)
    assert rates["trir"].ytd.rate == pytest.approx(2 * 200000 / 4000)
    damage = rates["property_equipment_damage"].ytd
    assert (damage.events, damage.property_damage, damage.equipment_damage_failure) == (3, 2, 1)
    # March 2098 - February 2099.
    rolling = rates["trir"].rolling
    assert (rolling.events, rolling.hours) == (4, 10 * 1000 + 2 * 2000)
    assert rates["lopc"].rolling.events == 0
    assert data.months[2].status == "reported"
    assert data.months[2].counts.lopc == 5
    annual = {a.year: a for a in data.annual_trir}
    assert (annual[2098].events, annual[2098].partial) == (2, False)
    assert (annual[2099].through_month, annual[2099].partial) == (2, True)


def test_rates_before_2026_read_legacy_counts(
    session: Session, repository: NonCommittingRepository
) -> None:
    close_months(repository, 2003, range(1, 13), 1000)
    close_months(repository, 2004, range(1, 3), 1000)
    typed = {
        (2003, 6, "recordable"): 2,
        (2004, 2, "property_equipment_damage"): 3,
    }
    periods = [(2003, m) for m in range(1, 13)] + [(2004, 1), (2004, 2)]
    for year, month in periods:
        for name, category in LEGACY_CATEGORIES.items():
            if (year, month, name) == (2004, 1, "lopc"):
                continue  # Left blank: not confirmed, even though the month is closed.
            value = typed.get((year, month, name), 0)
            store_value(session, "performance_legacy", category, year, month, value)
    # Ignored: years before 2026 do not read Incident & Near Miss.
    store_value(session, "incidents", INCIDENT_CATEGORIES["lopc"], 2004, 1, 9)
    session.flush()

    data = service.dashboard(repository, 2004, through_month=None, now=NOW)

    assert data.count_source == "performance_legacy"
    rates = {k.measure: k for k in data.kpis}
    assert (rates["trir"].rolling.events, rates["trir"].rolling.hours) == (2, 12000)
    damage = rates["property_equipment_damage"].ytd
    assert (damage.events, damage.property_damage, damage.equipment_damage_failure) == (
        3,
        None,
        None,
    )
    lopc = rates["lopc"].ytd
    assert (lopc.available, lopc.events) == (False, None)
    assert [(m.year, m.month, m.reason) for m in lopc.ineligible_months] == [
        (2004, 1, "count_not_confirmed")
    ]
