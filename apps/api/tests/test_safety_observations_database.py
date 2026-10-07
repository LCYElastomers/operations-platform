"""PostgreSQL integration tests for Safety Observations (migration 0004).

Enabled by TEST_DATABASE_URL (see test_moisture_database.py). Each test runs in
a transaction that is rolled back. Observations use 2003 dates and audit
queries filter on the observation entity type, so other rows are never read.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.observations import service
from app.safety.observations.models import Observation, ObservationCategory
from app.safety.observations.repository import DatabaseObservationRepository, ObservationFilter
from app.safety.observations.schemas import ObservationInput, ObservationUpdate

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
DAY = dt.date(2003, 5, 14)

EXPECTED_CATEGORIES = [
    ("building", "Building"),
    ("chemical", "Chemical"),
    ("confined_space", "Confined Space"),
    ("electrical", "Electrical"),
    ("ergonomics", "Ergonomics"),
    ("fire", "Fire"),
    ("fire_system", "Fire System"),
    ("forklift", "Forklift"),
    ("housekeeping", "Housekeeping"),
    ("loto", "LOTO"),
    ("material_defect", "Material Defect"),
    ("material_handling_lifting", "Material Handling or Lifting"),
    ("non_work_related", "Non-Work Related"),
    ("ppe", "PPE"),
    ("respiratory_protection", "Respiratory Protection"),
    ("slip_trip_fall", "Slip, Trip, Fall"),
    ("stairs_ladders", "Stairs, Ladders"),
    ("tools_equipment", "Tools & Equipment"),
    ("vehicle_company_owned", "Vehicle, Company Owned"),
    ("vehicle_not_company_owned", "Vehicle, Not Company Owned"),
    ("walking_working_surface", "Walking Working Surface"),
    ("work_at_elevation", "Work at Elevation"),
    ("crane", "Crane"),
]


class NonCommittingRepository(DatabaseObservationRepository):
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


def category_id(repository: DatabaseObservationRepository, code: str) -> int:
    return next(c.id for c in repository.categories() if c.code == code)


def observation_input(repository: DatabaseObservationRepository, **overrides: Any) -> Any:
    data: dict[str, Any] = {
        "observedOn": DAY.isoformat(),
        "outcome": "unsafe",
        "kind": "condition",
        "categoryId": category_id(repository, "housekeeping"),
        "areaLocation": "Dock 3",
        "description": "Spill near drain",
        **overrides,
    }
    model = ObservationUpdate if "expectedUpdatedAt" in data else ObservationInput
    return model.model_validate(data)


def observation_audit(session: Session) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == service.AUDIT_ENTITY_TYPE)
            .where(AuditEvent.actor_id.in_(["db-tester", "db-second"]))
            .order_by(AuditEvent.id)
        )
    )


# Schema --------------------------------------------------------------------------


def test_tables_constraints_and_indexes(engine: Engine) -> None:
    inspector = inspect(engine)

    assert inspector.has_table("observation_categories", schema="safety")
    assert inspector.has_table("observations", schema="safety")
    assert [
        (fk["name"], fk["constrained_columns"], fk["referred_table"])
        for fk in inspector.get_foreign_keys("observations", schema="safety")
    ] == [("fk_observations_category", ["category_id"], "observation_categories")]
    assert {c["name"] for c in inspector.get_check_constraints("observations", "safety")} == {
        "ck_observations_outcome",
        "ck_observations_kind",
        "ck_observations_observed_on",
        "ck_observations_area_location",
        "ck_observations_description",
        "ck_observations_corrective_action",
    }
    assert {i["name"] for i in inspector.get_indexes("observations", "safety")} == {
        "ix_observations_observed_on",
        "ix_observations_category_id",
    }
    assert [
        (u["name"], u["column_names"])
        for u in inspector.get_unique_constraints("observation_categories", "safety")
    ] == [("uq_observation_categories_code", ["code"])]
    columns = {c["name"]: c for c in inspector.get_columns("observations", "safety")}
    nullable = {name for name, column in columns.items() if column["nullable"]}
    assert nullable == {"area_location", "description", "corrective_action"}


def test_categories_are_seeded_in_display_order(
    repository: DatabaseObservationRepository,
) -> None:
    categories = repository.categories()

    assert [(c.code, c.name) for c in categories] == EXPECTED_CATEGORIES
    assert all(c.active for c in categories)


def test_legacy_definitions_are_seeded_without_values(session: Session) -> None:
    sections = session.scalars(
        select(MetricSection)
        .where(MetricSection.metric_set == "observations_legacy")
        .order_by(MetricSection.display_order)
    ).all()

    assert [s.code for s in sections] == [
        "safe_by_category",
        "unsafe_by_category",
        "act_condition",
        "total_observations",
    ]
    by_section = {
        s.code: set(
            session.scalars(select(MetricCategory.code).where(MetricCategory.section_id == s.id))
        )
        for s in sections
    }
    assert "fire" in by_section["safe_by_category"]
    assert "fire_system" not in by_section["safe_by_category"]
    assert "fire_system" in by_section["unsafe_by_category"]
    assert "fire" not in by_section["unsafe_by_category"]
    assert len(by_section["safe_by_category"]) == len(by_section["unsafe_by_category"]) == 22
    legacy_values = session.scalar(
        select(MonthlyMetricValue.id)
        .join(MetricCategory, MetricCategory.id == MonthlyMetricValue.category_id)
        .join(MetricSection, MetricSection.id == MetricCategory.section_id)
        .where(MetricSection.metric_set == "observations_legacy")
        .limit(1)
    )
    assert legacy_values is None


# Service round trip ----------------------------------------------------------------


def test_create_update_delete_round_trip_with_audit(
    session: Session, repository: NonCommittingRepository
) -> None:
    record = service.create_observation(
        repository, observation_input(repository), actor_id="db-tester", now=NOW
    )
    assert record.category_code == "housekeeping"
    assert record.values.description == "Spill near drain"
    assert record.created_by == record.updated_by == "db-tester"

    later = NOW + dt.timedelta(minutes=5)
    updated = service.update_observation(
        repository,
        record.id,
        observation_input(
            repository,
            outcome="safe",
            kind="act",
            categoryId=category_id(repository, "fire_system"),
            description=None,
            expectedUpdatedAt=record.updated_at.isoformat(),
        ),
        actor_id="db-second",
        now=later,
    )
    assert (updated.values.outcome, updated.category_code) == ("safe", "fire_system")
    assert updated.values.description is None
    assert (updated.created_by, updated.updated_by) == ("db-tester", "db-second")
    assert updated.updated_at == later

    service.delete_observation(repository, record.id, actor_id="db-second", now=later)
    assert repository.get(record.id) is None

    events = observation_audit(session)
    assert [(e.actor_id, e.action) for e in events] == [
        ("db-tester", "create"),
        ("db-second", "update"),
        ("db-second", "delete"),
    ]
    assert {e.entity_key for e in events} == {f"observations/{record.id}"}
    assert events[0].new_value is not None and events[0].new_value["category"] == "housekeeping"
    assert events[1].old_value == events[0].new_value
    assert events[1].new_value is not None and events[1].new_value["category"] == "fire_system"
    assert events[2].old_value == events[1].new_value
    assert len({e.change_set_id for e in events}) == 3
    ids = [e.id for e in events]
    missing_sides = session.execute(
        text(
            "SELECT action, old_value IS NULL, new_value IS NULL FROM core.audit_events "
            "WHERE id = ANY(:ids) ORDER BY id"
        ),
        {"ids": ids},
    ).all()
    assert [tuple(r) for r in missing_sides] == [
        ("create", True, False),
        ("update", False, False),
        ("delete", False, True),
    ]


def test_search_filters_counts_and_years(repository: NonCommittingRepository) -> None:
    ppe = category_id(repository, "ppe")
    for day, outcome, kind, category in [
        (dt.date(2003, 1, 31), "safe", "act", ppe),
        (dt.date(2003, 2, 1), "unsafe", "condition", ppe),
        (dt.date(2003, 2, 28), "safe", "condition", category_id(repository, "fire")),
    ]:
        service.create_observation(
            repository,
            observation_input(
                repository, observedOn=day.isoformat(), outcome=outcome, kind=kind,
                categoryId=category,
            ),
            actor_id="db-tester",
            now=NOW,
        )  # fmt: skip

    february = service.period(2003, 2)
    records, total = repository.search(february, limit=10, offset=0)
    assert total == 2
    assert [r.values.observed_on for r in records] == [dt.date(2003, 2, 28), dt.date(2003, 2, 1)]

    year = service.period(2003)
    records, total = repository.search(
        ObservationFilter(year.observed_from, year.observed_to, category_id=ppe),
        limit=1,
        offset=1,
    )
    assert total == 2
    assert [r.values.observed_on for r in records] == [dt.date(2003, 1, 31)]

    summary = service.summarize(repository, year=2003, month=None)
    assert summary.counts.total == 3
    assert (summary.counts.safe_act, summary.counts.safe_condition) == (1, 1)
    assert summary.counts.unsafe_condition == 1
    by_code = {c.code: c for c in summary.categories}
    assert (by_code["ppe"].safe, by_code["ppe"].unsafe) == (1, 1)
    assert by_code["fire_system"].total == 0

    dashboard = service.dashboard(repository, year=2003, today=NOW.date())
    assert [m.counts.total if m.counts else None for m in dashboard.months][:3] == [1, 2, 0]
    assert 2003 in dashboard.years_with_data


def test_stale_update_is_a_conflict(repository: NonCommittingRepository) -> None:
    record = service.create_observation(
        repository, observation_input(repository), actor_id="db-tester", now=NOW
    )

    with pytest.raises(service.EditConflictError):
        service.update_observation(
            repository,
            record.id,
            observation_input(repository, outcome="safe", expectedUpdatedAt="2003-01-01T00:00:00Z"),
            actor_id="db-tester",
            now=NOW,
        )


def test_retired_categories_cannot_be_chosen(
    session: Session, repository: NonCommittingRepository
) -> None:
    crane = session.get(ObservationCategory, category_id(repository, "crane"))
    assert crane is not None
    crane.active = False
    session.flush()

    assert "crane" not in [c.code for c in service.active_categories(repository)]
    with pytest.raises(service.UnknownCategoryError):
        service.create_observation(
            repository,
            observation_input(repository, categoryId=crane.id),
            actor_id="db-tester",
            now=NOW,
        )


# Database constraints ------------------------------------------------------------


def _row(category: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "observed_on": DAY,
        "outcome": "safe",
        "kind": "act",
        "category_id": category,
        "created_at": NOW,
        "created_by": "db-tester",
        "updated_at": NOW,
        "updated_by": "db-tester",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"outcome": "Safe"}, "ck_observations_outcome"),
        ({"kind": "behaviour"}, "ck_observations_kind"),
        ({"observed_on": dt.date(1999, 12, 31)}, "ck_observations_observed_on"),
        ({"area_location": "   "}, "ck_observations_area_location"),
        ({"area_location": "x" * 201}, "ck_observations_area_location"),
        ({"description": ""}, "ck_observations_description"),
        ({"corrective_action": "x" * 2001}, "ck_observations_corrective_action"),
        ({"category_id": 999_999}, "fk_observations_category"),
    ],
)
def test_database_rejects_invalid_rows(
    session: Session,
    repository: DatabaseObservationRepository,
    overrides: dict[str, object],
    constraint: str,
) -> None:
    housekeeping = category_id(repository, "housekeeping")

    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(Observation).values(_row(housekeeping, **overrides)))


def test_category_codes_are_unique(session: Session) -> None:
    with pytest.raises(IntegrityError, match="uq_observation_categories_code"):
        session.execute(
            insert(ObservationCategory).values(code="fire", name="Fire again", display_order=99)
        )
