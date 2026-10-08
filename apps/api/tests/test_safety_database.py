"""PostgreSQL integration tests for Safety monthly metrics and platform audit events.

Enabled by TEST_DATABASE_URL (see test_moisture_database.py). The role needs
USAGE and CREATE on `safety` (or CREATE on the database).
"""

import datetime as dt
from collections.abc import Iterator

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, func, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.safety import analytics, service
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.repository import DatabaseSafetyMetricsRepository
from app.safety.schemas import CellChange
from app.safety.service import EditConflictError

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 6, 12, 0, tzinfo=dt.UTC)


class NonCommittingRepository(DatabaseSafetyMetricsRepository):
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


def category_id(repository: DatabaseSafetyMetricsRepository, section: str, code: str) -> int:
    for s in repository.sections("incidents"):
        if s.code == section:
            return next(c.id for c in s.categories if c.code == code)
    raise AssertionError(f"{section}/{code} not seeded")


def test_tables_are_created_in_safety_schema(engine: Engine) -> None:
    inspector = inspect(engine)

    for table in ("metric_sections", "metric_categories", "monthly_metric_values"):
        assert inspector.has_table(table, schema="safety")
    assert inspector.has_table("audit_events", schema="core")
    uniques = inspector.get_unique_constraints("monthly_metric_values", "safety")
    assert [(u["name"], u["column_names"]) for u in uniques] == [
        (
            "uq_monthly_metric_values_category_year_month",
            ["category_id", "reporting_year", "reporting_month"],
        )
    ]


def test_incident_definitions_are_seeded_in_display_order(
    repository: DatabaseSafetyMetricsRepository,
) -> None:
    sections = repository.sections("incidents")

    assert [(s.code, s.name) for s in sections] == [
        ("incident_near_miss_totals", "Incident & Near Miss Totals"),
        ("incident_classification", "Incident Classification"),
        ("lopc", "LOPC"),
        ("property_equipment_damage", "Property / Equipment Damage"),
        ("pit", "PIT"),
        ("psif", "PSIF"),
    ]
    assert [(c.code, c.name) for c in sections[0].categories] == [
        ("near_miss", "Near Miss"),
        ("incident", "Incident"),
    ]
    assert [c.name for c in sections[1].categories] == [
        "First Aid",
        "Recordable Injury",
        "Lost Time Injury",
        "Restricted",
        "Occupational Illness",
        "Hazardous Condition",
        "Spill / Release",
        "Fire",
        "PIT Accident",
        "Property Damage",
        "Equipment Damage / Failure",
        "Non-Work Related",
        "Regulatory",
    ]
    for section in sections[2:]:
        assert [c.code for c in section.categories] == [section.code]


def test_foreign_keys_and_check_constraints(engine: Engine) -> None:
    inspector = inspect(engine)

    fks = {
        table: [
            (fk["name"], fk["constrained_columns"], fk["referred_table"])
            for fk in inspector.get_foreign_keys(table, schema="safety")
        ]
        for table in ("metric_categories", "monthly_metric_values")
    }
    assert fks == {
        "metric_categories": [("fk_metric_categories_section", ["section_id"], "metric_sections")],
        "monthly_metric_values": [
            ("fk_monthly_metric_values_category", ["category_id"], "metric_categories")
        ],
    }
    checks = {c["name"] for c in inspector.get_check_constraints("monthly_metric_values", "safety")}
    assert checks == {
        "ck_monthly_metric_values_reporting_month",
        "ck_monthly_metric_values_reporting_year",
        "ck_monthly_metric_values_value_non_negative",
    }
    assert {c["name"] for c in inspector.get_check_constraints("audit_events", "core")} == {
        "ck_audit_events_action"
    }
    assert {i["name"] for i in inspector.get_indexes("audit_events", "core")} == {
        "ix_audit_events_entity",
        "ix_audit_events_occurred_at_desc",
    }


def test_no_values_are_seeded(session: Session) -> None:
    assert session.scalars(select(MonthlyMetricValue)).all() == []


def test_inactive_categories_are_hidden(
    session: Session, repository: DatabaseSafetyMetricsRepository
) -> None:
    fire = category_id(repository, "incident_classification", "fire")
    session.get(MetricCategory, fire).active = False  # type: ignore[union-attr]
    session.flush()

    names = [c.code for c in repository.sections("incidents")[1].categories]

    assert "fire" not in names


def test_save_round_trip_with_audit(session: Session, repository: NonCommittingRepository) -> None:
    first_aid = category_id(repository, "incident_classification", "first_aid")
    near_miss = category_id(repository, "incident_near_miss_totals", "near_miss")

    save = service.save_changes(
        repository,
        metric_set="incidents",
        year=2026,
        changes=[
            CellChange(category_id=first_aid, month=1, value=2, previous_value=None),
            CellChange(category_id=near_miss, month=1, value=0, previous_value=None),
        ],
        actor_id="tester",
        now=NOW,
    )
    service.save_changes(
        repository,
        metric_set="incidents",
        year=2026,
        changes=[
            CellChange(category_id=first_aid, month=1, value=3, previous_value=2),
            CellChange(category_id=near_miss, month=1, value=None, previous_value=0),
        ],
        actor_id="second",
        now=NOW + dt.timedelta(minutes=5),
    )

    metrics = service.load_metrics(repository, metric_set="incidents", year=2026, can_edit=True)
    totals, classification = metrics.sections[0], metrics.sections[1]
    assert classification.categories[0].values[0] == 3
    assert classification.categories[0].ytd == 3
    near, incident = totals.categories
    assert near.ytd is None
    assert incident.ytd is None, "Incident is explicit, never summed from classifications"
    (row,) = session.scalars(select(MonthlyMetricValue)).all()
    assert (row.created_by, row.updated_by, row.value) == ("tester", "second", 3)

    events = session.scalars(select(AuditEvent).order_by(AuditEvent.id)).all()
    assert [(e.actor_id, e.action, e.old_value, e.new_value) for e in events] == [
        ("tester", "create", None, {"value": 2}),
        ("tester", "create", None, {"value": 0}),
        ("second", "update", {"value": 2}, {"value": 3}),
        ("second", "delete", {"value": 0}, None),
    ]
    assert events[0].change_set_id == save.change_set_id
    assert events[0].entity_key == "incidents/incident_classification/first_aid/2026-01"
    # The ORM reads JSON null back as None too; check SQL NULL at the database.
    missing_sides = session.execute(
        text(
            "SELECT action, old_value IS NULL, new_value IS NULL FROM core.audit_events ORDER BY id"
        )
    ).all()
    assert [tuple(r) for r in missing_sides] == [
        ("create", True, False),
        ("create", True, False),
        ("update", False, False),
        ("delete", False, True),
    ]


def test_analytics_read_the_seeded_definitions_and_write_nothing(
    session: Session, repository: NonCommittingRepository
) -> None:
    # A year no other data uses, so the test is independent of stored values.
    year = 2099
    assert not session.scalars(
        select(MonthlyMetricValue).where(MonthlyMetricValue.reporting_year == year)
    ).first()

    def cell(section: str, code: str, month: int, value: int) -> CellChange:
        return CellChange(
            category_id=category_id(repository, section, code),
            month=month,
            value=value,
            previous_value=None,
        )

    service.save_changes(
        repository,
        metric_set="incidents",
        year=year,
        changes=[
            cell("incident_near_miss_totals", "incident", 1, 2),
            cell("lopc", "lopc", 1, 1),
            cell("incident_classification", "spill_release", 1, 1),
            cell("incident_classification", "pit_accident", 1, 1),
            cell("pit", "pit", 1, 1),
            cell("incident_classification", "property_damage", 1, 1),
            cell("incident_classification", "equipment_damage_failure", 1, 2),
            cell("property_equipment_damage", "property_equipment_damage", 1, 1),
        ],
        actor_id="tester",
        now=NOW,
    )
    audit_rows = session.scalar(select(func.count()).select_from(AuditEvent))
    value_rows = session.scalar(select(func.count()).select_from(MonthlyMetricValue))

    result = analytics.load_analytics(
        repository, year=year, through_month=2, now=dt.datetime(2099, 3, 1, 18, tzinfo=dt.UTC)
    )

    assert {kpi.key: kpi.value for kpi in result.kpis} == {
        "incidents": 2,
        "near_misses": None,
        "lopc": 1,
        "psif": None,
        # pit_accident only; the pit section's 1 is not added. Property 1 +
        # equipment 2; the stale combined section's 1 is not read.
        "pit": 1,
        "combined_damage": 3,
    }
    assert (result.pit.code, result.pit.total) == ("pit_accident", 1)
    assert result.combined_damage.values == [3, None]
    assert [row.name for row in result.classifications][-1] == "PSIF"
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_rows
    assert session.scalar(select(func.count()).select_from(MonthlyMetricValue)) == value_rows


def test_stale_previous_value_is_a_conflict(repository: NonCommittingRepository) -> None:
    first_aid = category_id(repository, "incident_classification", "first_aid")
    service.save_changes(
        repository,
        metric_set="incidents",
        year=2026,
        changes=[CellChange(category_id=first_aid, month=4, value=1, previous_value=None)],
        actor_id="tester",
        now=NOW,
    )

    with pytest.raises(EditConflictError):
        service.save_changes(
            repository,
            metric_set="incidents",
            year=2026,
            changes=[CellChange(category_id=first_aid, month=4, value=5, previous_value=None)],
            actor_id="tester",
            now=NOW,
        )


def _value_row(category: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "category_id": category,
        "reporting_year": 2026,
        "reporting_month": 1,
        "value": 1,
        "created_by": "t",
        "updated_by": "t",
    }
    row.update(overrides)
    return row


def test_duplicate_cells_are_rejected_by_the_database(
    session: Session, repository: DatabaseSafetyMetricsRepository
) -> None:
    first_aid = category_id(repository, "incident_classification", "first_aid")
    session.execute(insert(MonthlyMetricValue).values(_value_row(first_aid)))

    with pytest.raises(IntegrityError, match="uq_monthly_metric_values_category_year_month"):
        session.execute(insert(MonthlyMetricValue).values(_value_row(first_aid, value=2)))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"value": -1}, "value_non_negative"),
        ({"reporting_month": 13}, "reporting_month"),
        ({"reporting_year": 1999}, "reporting_year"),
    ],
)
def test_check_constraints(
    session: Session,
    repository: DatabaseSafetyMetricsRepository,
    overrides: dict[str, object],
    constraint: str,
) -> None:
    first_aid = category_id(repository, "incident_classification", "first_aid")

    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(MonthlyMetricValue).values(_value_row(first_aid, **overrides)))


def test_section_codes_are_unique_per_metric_set(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            insert(MetricSection).values(
                metric_set="incidents",
                code="incident_classification",
                name="Duplicate",
                display_order=99,
            )
        )
