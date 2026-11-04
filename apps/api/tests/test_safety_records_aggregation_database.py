"""PostgreSQL tests for the derived monthly values rebuilt from records (migration 0019).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back; records use 2003 dates.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.records import aggregation, service
from app.safety.records.models import IncidentRecord
from app.safety.records.repository import RecordRepository
from app.safety.records.schemas import ReclassifyRequest, RecordCreate, RecordUpdate, VoidRequest
from app.safety.records.tags import BODY_PARTS, EVENT_CAUSES, INJURY_CAUSES, TagSpec

pytestmark = requires_postgres

NOW = dt.datetime(2026, 11, 2, 15, 0, tzinfo=dt.UTC)
ACTOR = service.Actor("db-aggregation-tester", NOW)


class NonCommittingRecords(RecordRepository):
    def commit(self) -> None:
        self._session.flush()

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
def repository(session: Session) -> NonCommittingRecords:
    return NonCommittingRecords(session)


def class_ids(repository: RecordRepository) -> dict[str, int]:
    return {o.code: o.id for o in repository.classifications()}


def area_ids(repository: RecordRepository) -> dict[str, int]:
    return {o.code: o.id for o in repository.areas()}


def tag_ids(repository: RecordRepository, tag: TagSpec, *codes: str) -> list[int]:
    by_code = {o.code: o.id for o in repository.tag_options(tag)}
    return [by_code[code] for code in codes]


def create(
    repository: RecordRepository, *, actor: service.Actor = ACTOR, **fields: Any
) -> int:
    data: dict[str, Any] = {
        "eventType": "incident",
        "incidentDate": "2003-01-14",
        "description": "ZZ test event.",
        **fields,
    }
    return service.create(repository, RecordCreate.model_validate(data), actor).record.id


def edit(
    repository: RecordRepository,
    record_id: int,
    *,
    actor: service.Actor = ACTOR,
    **changes: Any,
) -> Any:
    row = repository.get(record_id)
    assert row is not None
    r = row.record
    body: dict[str, Any] = {
        "incidentNumber": r.incident_number,
        "incidentDate": r.incident_date.isoformat(),
        "description": r.description,
        "areaId": r.area_id,
        "classificationCategoryId": r.classification_category_id,
        "version": r.version,
        **changes,
    }
    return service.update(repository, record_id, RecordUpdate.model_validate(body), actor)


def stored_totals(session: Session, year: int, month: int) -> dict[tuple[str, str], int]:
    """(section, category) -> values written by rebuild (totals only)."""
    s, c, v = MetricSection, MetricCategory, MonthlyMetricValue
    rows = session.execute(
        select(s.code, c.code, v.value)
        .join(c, c.section_id == s.id)
        .join(v, v.category_id == c.id)
        .where(
            s.metric_set == aggregation.INCIDENTS_METRIC_SET,
            s.code.in_(aggregation.DERIVED_SECTIONS),
            v.reporting_year == year,
            v.reporting_month == month,
        )
    ).all()
    return {(section, category): value for section, category, value in rows}


def expected(session: Session, year: int, month: int) -> dict[tuple[str, str], int]:
    """Record-derived expected counts (not necessarily stored in monthly cells)."""
    categories = aggregation._load_categories(session, aggregation.RECORD_EXPECTED_SECTIONS)
    counts = aggregation.month_counts(session, categories, year, month)
    return {(c.section, c.code): counts.get(c.id, 0) for c in categories.all}


def stored(session: Session, year: int, month: int) -> dict[tuple[str, str], int]:
    """Alias used by totals-focused tests."""
    return stored_totals(session, year, month)


def test_each_counting_rule_feeds_its_derived_category(
    session: Session, repository: RecordRepository
) -> None:
    classes, areas = class_ids(repository), area_ids(repository)
    create(
        repository,
        areaId=areas["300"],
        classificationCategoryId=classes["first_aid"],
        injuryCauseCategoryIds=tag_ids(repository, INJURY_CAUSES, "caught_between", "struck_by"),
        bodyPartCategoryIds=tag_ids(repository, BODY_PARTS, "hand"),
        eventCauseCategoryIds=tag_ids(repository, EVENT_CAUSES, "human_performance"),
    )
    create(
        repository,
        areaId=areas["300"],
        classificationCategoryId=classes["spill_release"],
        additionalClassificationIds=[
            classes["property_damage"],
            classes["equipment_damage_failure"],
        ],
        lopcDetails={"contributingFactorCode": "mechanical_integrity"},
        eventCauseCategoryIds=tag_ids(repository, EVENT_CAUSES, "procedures", "human_performance"),
    )
    create(
        repository,
        eventType="near_miss",
        areaId=areas["100"],
        classificationCategoryId=classes["pit_accident"],
        seriousRiskDetails={"isPsif": True},
    )

    totals = stored_totals(session, 2003, 1)
    assert totals[("incident_near_miss_totals", "incident")] == 2
    assert totals[("incident_near_miss_totals", "near_miss")] == 1

    values = expected(session, 2003, 1)
    assert values[("incidents_by_area", "300")] == 2
    assert values[("incidents_by_area", "100")] == 0
    assert values[("near_misses_by_area", "100")] == 1
    classification = {
        code: n for (section, code), n in values.items() if section == "incident_classification"
    }
    assert classification["first_aid"] == 1
    assert classification["spill_release"] == 1
    assert classification["property_damage"] == 1
    assert classification["equipment_damage_failure"] == 1
    assert classification["pit_accident"] == 1
    assert classification["fire"] == 0
    assert values[("injury_cause", "caught_between")] == 1
    assert values[("injury_cause", "struck_by")] == 1
    assert values[("injury_cause", "caught_in")] == 0
    assert values[("body_part", "hand")] == 1
    assert values[("near_miss_cause", "human_performance")] == 2
    assert values[("near_miss_cause", "procedures")] == 1
    assert values[("lopc", "lopc")] == 1
    assert values[("lopc_contributing_factor", "mechanical_integrity")] == 1
    # Property Damage and Equipment Damage / Failure on one record count once.
    assert values[("property_equipment_damage", "property_equipment_damage")] == 1
    assert values[("pit", "pit")] == 1
    assert values[("psif", "psif")] == 1


def test_void_move_and_reclassify_rebuild_from_active_records_only(
    session: Session, repository: RecordRepository
) -> None:
    january = create(repository, incidentDate="2003-01-10")
    create(repository, incidentDate="2003-01-11")
    assert stored(session, 2003, 1)[("incident_near_miss_totals", "incident")] == 2

    # Moving the date rebuilds both months.
    edit(repository, january, incidentDate="2003-02-10")
    assert stored(session, 2003, 1)[("incident_near_miss_totals", "incident")] == 1
    assert stored(session, 2003, 2)[("incident_near_miss_totals", "incident")] == 1

    service.void(repository, january, VoidRequest(version=2, reason="ZZ duplicate"), ACTOR)
    assert stored(session, 2003, 2)[("incident_near_miss_totals", "incident")] == 0

    # The replacement counts once; the superseded original not at all.
    original = create(repository, incidentDate="2003-03-05")
    service.reclassify(
        repository,
        original,
        ReclassifyRequest.model_validate(
            {
                "version": 1,
                "reason": "ZZ wrong type",
                "replacement": {"incidentDate": "2003-04-02", "description": "ZZ replacement."},
            }
        ),
        ACTOR,
    )
    march, april = stored(session, 2003, 3), stored(session, 2003, 4)
    assert march[("incident_near_miss_totals", "incident")] == 0
    assert march[("incident_near_miss_totals", "near_miss")] == 0
    assert april[("incident_near_miss_totals", "incident")] == 0
    assert april[("incident_near_miss_totals", "near_miss")] == 1


def _incident_total(session: Session, year: int, month: int) -> int:
    return stored(session, year, month).get(("incident_near_miss_totals", "incident"), 0)


def _incident_ytd(session: Session, year: int) -> int:
    return sum(_incident_total(session, year, month) for month in range(1, 13))


def test_editing_across_the_year_boundary_moves_reporting_contributions(
    session: Session, repository: RecordRepository
) -> None:
    """Register-style edit (no month context): same record ID moves from 2026 into 2027.

    Month/YTD checks are deltas from the post-create rebuild so a shared
    database that already has 2026 rows remains valid.
    """
    actor = service.Actor("db-aggregation-tester", dt.datetime(2027, 1, 15, 18, 0, tzinfo=dt.UTC))

    record_id = create(repository, actor=actor, incidentDate="2026-12-31")
    other_id = create(repository, actor=actor, incidentDate="2026-12-15")
    assert other_id != record_id

    after_create_dec = _incident_total(session, 2026, 12)
    after_create_jan = _incident_total(session, 2027, 1)
    after_create_ytd_2026 = _incident_ytd(session, 2026)
    after_create_ytd_2027 = _incident_ytd(session, 2027)
    assert after_create_dec >= 2

    edited = edit(repository, record_id, actor=actor, incidentDate="2027-01-01")
    assert edited.record.id == record_id
    assert edited.record.incident_date == dt.date(2027, 1, 1)
    out = service.record_out(edited)
    assert (out.reporting_year, out.reporting_month) == (2027, 1)

    # December contribution for the moved record is removed; January gains it.
    assert _incident_total(session, 2026, 12) == after_create_dec - 1
    assert _incident_total(session, 2027, 1) == after_create_jan + 1
    assert _incident_ytd(session, 2026) == after_create_ytd_2026 - 1
    assert _incident_ytd(session, 2027) == after_create_ytd_2027 + 1

    # One physical row; it cannot remain dated in both years.
    assert session.scalar(select(func.count()).select_from(IncidentRecord).where(IncidentRecord.id == record_id)) == 1
    assert (
        session.scalar(
            select(func.count())
            .select_from(IncidentRecord)
            .where(IncidentRecord.id == record_id, IncidentRecord.incident_date == dt.date(2026, 12, 31))
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(IncidentRecord)
            .where(IncidentRecord.id == record_id, IncidentRecord.incident_date == dt.date(2027, 1, 1))
        )
        == 1
    )

    # Existing audit trail records the previous and corrected dates (reporting
    # period is derived from incident_date, not stored separately).
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_key == service.entity_key(record_id))
            .order_by(AuditEvent.id)
        )
    )
    updates = [e for e in events if e.action == "update"]
    assert updates
    assert updates[-1].old_value["incident_date"] == "2026-12-31"
    assert updates[-1].new_value["incident_date"] == "2027-01-01"
    assert updates[-1].actor_id == actor.actor_id
    assert updates[-1].occurred_at is not None


def test_removing_first_aid_clears_injury_causes_and_body_parts(
    session: Session, repository: RecordRepository
) -> None:
    classes = class_ids(repository)
    record_id = create(
        repository,
        classificationCategoryId=classes["first_aid"],
        injuryCauseCategoryIds=tag_ids(repository, INJURY_CAUSES, "struck_by"),
        bodyPartCategoryIds=tag_ids(repository, BODY_PARTS, "hand"),
    )
    assert expected(session, 2003, 1)[("injury_cause", "struck_by")] == 1

    row = edit(repository, record_id, classificationCategoryId=classes["hazardous_condition"])

    out = service.record_out(row)
    assert out.injury_cause_category_ids == [] and out.body_part_category_ids == []
    values = expected(session, 2003, 1)
    assert values[("injury_cause", "struck_by")] == 0 and values[("body_part", "hand")] == 0


def test_first_aid_needs_an_injury_cause_and_a_body_part(repository: RecordRepository) -> None:
    classes = class_ids(repository)
    first_aid = {"classificationCategoryId": classes["first_aid"]}

    with pytest.raises(service.RecordRuleError) as missing:
        create(repository, **first_aid)
    assert missing.value.error == "first_aid_needs_tags"

    with pytest.raises(service.RecordRuleError) as no_body:
        create(
            repository,
            injuryCauseCategoryIds=tag_ids(repository, INJURY_CAUSES, "struck_by"),
            **first_aid,
        )
    assert no_body.value.field == "bodyPartCategoryIds"

    with pytest.raises(service.RecordRuleError) as not_first_aid:
        create(
            repository,
            classificationCategoryId=classes["fire"],
            injuryCauseCategoryIds=tag_ids(repository, INJURY_CAUSES, "struck_by"),
        )
    assert not_first_aid.value.error == "tag_needs_first_aid"


def test_ytd_equals_the_sum_of_the_twelve_months(
    session: Session, repository: RecordRepository
) -> None:
    create(repository, incidentDate="2003-01-10")
    create(repository, incidentDate="2003-03-15")
    create(repository, incidentDate="2003-03-20")
    create(repository, eventType="near_miss", incidentDate="2003-12-01")

    key = ("incident_near_miss_totals", "incident")
    months = [stored(session, 2003, month).get(key, 0) for month in range(1, 13)]
    assert months == [1, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert sum(months) == 3
    near_key = ("incident_near_miss_totals", "near_miss")
    near = [stored(session, 2003, month).get(near_key, 0) for month in range(1, 13)]
    assert sum(near) == 1


def test_historical_first_aid_without_tags_remains_readable(
    repository: RecordRepository,
) -> None:
    """Migration does not backfill tags; older First Aid rows must still load."""
    classes = class_ids(repository)
    record_id = create(repository, classificationCategoryId=classes["fire"])
    # Bypass the service to simulate a pre-0019 First Aid row with no tags.
    row = repository.get(record_id)
    assert row is not None
    row.record.classification_category_id = classes["first_aid"]
    repository._session.flush()
    loaded = repository.get(record_id)
    assert loaded is not None
    out = service.record_out(loaded)
    assert out.classification_code == "first_aid"
    assert out.injury_cause_category_ids == []
    assert out.body_part_category_ids == []


def test_august_lti_does_not_increment_recordable_injury_row(
    session: Session, repository: RecordRepository
) -> None:
    """One August Lost Time Injury → LTI 1, Recordable 0, TRIR cases 1."""
    from app.safety.trir_eligibility import trir_case_counts

    classes = class_ids(repository)
    create(
        repository,
        incidentDate="2003-08-12",
        classificationCategoryId=classes["lost_time_injury"],
    )
    values = expected(session, 2003, 8)
    assert values[("incident_classification", "lost_time_injury")] == 1
    assert values[("incident_classification", "recordable_injury")] == 0
    assert values[("incident_classification", "restricted")] == 0
    assert trir_case_counts(session, {2003}).get((2003, 8)) == 1


def test_create_rejects_recordable_plus_lost_time(
    repository: RecordRepository,
) -> None:
    classes = class_ids(repository)
    with pytest.raises(service.RecordRuleError) as raised:
        create(
            repository,
            classificationCategoryId=classes["recordable_injury"],
            additionalClassificationIds=[classes["lost_time_injury"]],
        )
    assert raised.value.error == "injury_outcome_conflict"


def test_overlapping_historical_tags_count_once_for_trir(
    session: Session, repository: RecordRepository
) -> None:
    from app.safety.records.detail_models import IncidentRecordClassification
    from app.safety.trir_eligibility import (
        overlapping_injury_outcome_records,
        trir_case_counts,
    )

    classes = class_ids(repository)
    record_id = create(
        repository,
        incidentDate="2003-08-15",
        classificationCategoryId=classes["lost_time_injury"],
    )
    # Simulate a legacy overlap the UI/API no longer allow.
    session.add(
        IncidentRecordClassification(
            incident_record_id=record_id,
            classification_category_id=classes["recordable_injury"],
        )
    )
    session.flush()
    overlaps = overlapping_injury_outcome_records(session)
    assert any(row["recordId"] == record_id for row in overlaps)
    assert trir_case_counts(session, {2003}).get((2003, 8)) == 1
