"""PostgreSQL tests for Incident and Near Miss records and TRIR history (migration 0009).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back. Records use 2003 dates and test-only numbers
(prefix ZZT), so stored data is never read or changed.
"""

import datetime as dt
import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, func, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.safety import service as metrics_service
from app.safety.records import legacy_import as records_import
from app.safety.records import narratives, service
from app.safety.records.models import IncidentRecord
from app.safety.records.repository import RecordFilter, RecordRepository
from app.safety.records.schemas import (
    ReclassifyRequest,
    RecordCreate,
    RecordFields,
    RecordUpdate,
    VoidRequest,
)
from app.safety.repository import DatabaseSafetyMetricsRepository
from app.safety.schemas import CellChange
from app.safety.trir import legacy_import as trir_import
from app.safety.trir.models import TrirAnnualFact
from app.safety.trir.repository import TrirRepository

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 8, 15, 0, tzinfo=dt.UTC)
ACTOR = service.Actor("db-records-tester", NOW)
API_ROOT = Path(__file__).resolve().parents[1]
TRIR_MAPPING = API_ROOT / "import_templates" / "safety_trir_experience_history_lcy_ehs.mapping.json"


def migration_0009() -> ModuleType:
    path = next((API_ROOT / "alembic" / "versions").glob("*-0009_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0009", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NonCommittingRecords(RecordRepository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.session = session

    def commit(self) -> None:
        self.session.flush()

    def rollback(self) -> None:
        pass


class NonCommittingTrir(TrirRepository):
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
def repository(session: Session) -> NonCommittingRecords:
    return NonCommittingRecords(session)


def option_id(options: list[Any], code: str) -> int:
    return next(o.id for o in options if o.code == code)


def create(repository: RecordRepository, **overrides: Any) -> int:
    data: dict[str, Any] = {
        "eventType": "incident",
        "incidentDate": "2003-01-14",
        "description": "ZZ test: operator slipped on wet grating.",
        **overrides,
    }
    return service.create(repository, RecordCreate.model_validate(data), ACTOR).record.id


def audit(session: Session, record_id: int) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_key == service.entity_key(record_id))
            .order_by(AuditEvent.id)
        )
    )


# Schema --------------------------------------------------------------------------


def test_tables_indexes_constraints_and_trigger(engine: Engine) -> None:
    inspector = inspect(engine)

    assert {i["name"] for i in inspector.get_indexes("incident_records", "safety")} == {
        "uq_incident_records_incident_number",
        "ix_incident_records_incident_date",
        "ix_incident_records_event_type_date",
        "ix_incident_records_area_date",
        "ix_incident_records_active_type_date",
        "ix_incident_records_related_incident_id",
    }
    assert {c["name"] for c in inspector.get_check_constraints("incident_records", "safety")} == {
        "ck_incident_records_event_type",
        "ck_incident_records_status",
        "ck_incident_records_source",
        "ck_incident_records_incident_date",
        "ck_incident_records_description",
        "ck_incident_records_incident_number",
        "ck_incident_records_status_reason",
        "ck_incident_records_inactive_has_reason",
        "ck_incident_records_reclassified_has_replacement",
        "ck_incident_records_related_not_self",
        "ck_incident_records_source_reference",
        "ck_incident_records_version",
    }
    assert {
        (f["name"], f["referred_table"], f["options"].get("ondelete"))
        for f in inspector.get_foreign_keys("incident_records", "safety")
    } == {
        ("fk_incident_records_area", "areas", "RESTRICT"),
        ("fk_incident_records_classification", "metric_categories", "RESTRICT"),
        ("fk_incident_records_related", "incident_records", "RESTRICT"),
    }
    columns = {c["name"] for c in inspector.get_columns("incident_records", "safety")}
    assert not any("month" in c or "year" in c for c in columns)
    trir_columns = {c["name"] for c in inspector.get_columns("trir_annual_facts", "safety")}
    assert not any("month" in c for c in trir_columns)
    with engine.connect() as connection:
        triggers = connection.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'safety.incident_records'::regclass "
                "AND NOT tgisinternal"
            )
        ).scalars()
        assert set(triggers) == {"trg_incident_records_classification_rule"}


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "event_type": "incident",
        "incident_date": dt.date(2003, 1, 1),
        "description": "ZZ row",
        "created_by": "t",
        "updated_by": "t",
        **overrides,
    }


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"event_type": "injury"}, "ck_incident_records_event_type"),
        ({"description": "   "}, "ck_incident_records_description"),
        ({"incident_number": "LCY 2026-040"}, "ck_incident_records_incident_number"),
        ({"incident_date": dt.date(1999, 12, 31)}, "ck_incident_records_incident_date"),
        ({"status": "voided"}, "ck_incident_records_inactive_has_reason"),
        (
            {"status": "reclassified", "status_reason": "x"},
            "ck_incident_records_reclassified_has_replacement",
        ),
        ({"source": "excel"}, "ck_incident_records_source"),
        ({"version": 0}, "ck_incident_records_version"),
    ],
)
def test_database_rejects_invalid_records(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(IncidentRecord).values(_row(**overrides)))


def test_database_rejects_a_classification_outside_incident_classification(
    session: Session, repository: RecordRepository
) -> None:
    near_miss_total = session.execute(
        text(
            "SELECT c.id FROM safety.metric_categories c JOIN safety.metric_sections s "
            "ON s.id = c.section_id WHERE s.code = 'incident_near_miss_totals' "
            "AND c.code = 'near_miss'"
        )
    ).scalar_one()
    with pytest.raises(IntegrityError, match="must be an Incident Classification") as error:
        session.execute(
            insert(IncidentRecord).values(_row(classification_category_id=near_miss_total))
        )
    assert error.value.orig.diag.constraint_name == "ck_incident_records_classification"  # type: ignore[union-attr]


def test_database_rejects_a_duplicate_number(session: Session) -> None:
    session.execute(insert(IncidentRecord).values(_row(incident_number="ZZT-2003-001")))
    with pytest.raises(IntegrityError, match="uq_incident_records_incident_number"):
        session.execute(insert(IncidentRecord).values(_row(incident_number="ZZT-2003-001")))


def test_downgrade_guard_refuses_while_records_exist(
    session: Session, repository: RecordRepository
) -> None:
    create(repository)
    with pytest.raises(DBAPIError, match="incident records exist"), session.begin_nested():
        session.execute(text(migration_0009().DOWNGRADE_GUARD))


@pytest.mark.empty_database
def test_downgrade_guard_refuses_while_trir_history_exists(session: Session) -> None:
    session.execute(
        insert(TrirAnnualFact).values(
            reporting_year=2003, source="fixture", created_by="t", updated_by="t"
        )
    )
    with pytest.raises(DBAPIError, match="TRIR history exists"), session.begin_nested():
        session.execute(text(migration_0009().DOWNGRADE_GUARD))


# Service -------------------------------------------------------------------------


def test_create_normalizes_audits_and_derives_the_month(
    session: Session, repository: RecordRepository
) -> None:
    areas, classes = repository.areas(), repository.classifications()
    record_id = create(
        repository,
        incidentNumber="zzt 2003-7",
        areaId=option_id(areas, "300"),
        classificationCategoryId=option_id(classes, "first_aid"),
        reportingYear=2003,
        reportingMonth=1,
    )

    row = repository.get(record_id)
    assert row is not None
    out = service.record_out(row)
    assert out.incident_number == "ZZT-2003-007"
    assert (out.reporting_year, out.reporting_month) == (2003, 1)
    assert (out.area_code, out.classification_code) == ("300", "first_aid")
    assert (out.status, out.source, out.version) == ("active", "manual", 1)
    assert "source_reference" not in out.model_dump()
    [event] = audit(session, record_id)
    assert (event.action, event.actor_id, event.entity_type) == (
        "create",
        ACTOR.actor_id,
        "safety.incident_record",
    )
    assert event.new_value is not None
    assert event.new_value["incident_number"] == "ZZT-2003-007"


def test_number_uniqueness_uses_the_normalized_form(repository: RecordRepository) -> None:
    create(repository, incidentNumber="ZZT-2003-040")

    with pytest.raises(service.RecordRuleError) as error:
        create(repository, incidentNumber="ZZT 2003-40")
    assert error.value.error == "duplicate_incident_number"


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        (
            {"incidentDate": "2003-02-01", "reportingYear": 2003, "reportingMonth": 1},
            "date_outside_month",
        ),
        ({"incidentDate": "2026-10-09"}, "future_date"),
        ({"description": "   "}, "blank_description"),
        ({"incidentNumber": "number 5"}, "invalid_incident_number"),
        ({"areaId": 2_000_000_000}, "invalid_area"),
        ({"classificationCategoryId": 2_000_000_000}, "invalid_classification"),
    ],
)
def test_invalid_records_are_refused_and_nothing_is_written(
    session: Session, repository: RecordRepository, overrides: dict[str, Any], error: str
) -> None:
    before = session.scalar(select(func.count()).select_from(IncidentRecord))
    with pytest.raises(service.RecordRuleError) as raised:
        create(repository, **overrides)
    assert raised.value.error == error
    assert session.scalar(select(func.count()).select_from(IncidentRecord)) == before


def test_update_with_version_conflict_and_audit(
    session: Session, repository: RecordRepository
) -> None:
    record_id = create(repository)
    edit = {
        "incidentDate": "2003-01-15",
        "description": "ZZ test: corrected description",
        "reportingYear": 2003,
        "reportingMonth": 1,
    }

    updated = service.update(
        repository, record_id, RecordUpdate.model_validate({**edit, "version": 1}), ACTOR
    )
    assert (updated.record.version, updated.record.incident_date) == (2, dt.date(2003, 1, 15))

    with pytest.raises(service.RecordConflictError) as conflict:
        service.update(
            repository, record_id, RecordUpdate.model_validate({**edit, "version": 1}), ACTOR
        )
    assert conflict.value.current.record.version == 2

    unchanged = service.update(
        repository, record_id, RecordUpdate.model_validate({**edit, "version": 2}), ACTOR
    )
    assert unchanged.record.version == 2
    events = audit(session, record_id)
    assert [e.action for e in events] == ["create", "update"]
    assert events[1].old_value is not None and events[1].new_value is not None
    assert events[1].old_value["description"] == "ZZ test: operator slipped on wet grating."
    assert events[1].new_value["description"] == "ZZ test: corrected description"


def test_edit_cannot_move_a_record_to_another_month(repository: RecordRepository) -> None:
    record_id = create(repository)
    request = RecordUpdate.model_validate(
        {
            "incidentDate": "2003-03-02",
            "description": "ZZ moved",
            "version": 1,
            "reportingYear": 2003,
            "reportingMonth": 1,
        }
    )
    with pytest.raises(service.RecordRuleError, match="January 2003"):
        service.update(repository, record_id, request, ACTOR)


def test_void_keeps_the_record_and_excludes_it(
    session: Session, repository: RecordRepository
) -> None:
    record_id = create(repository, incidentNumber="ZZT-2003-101")

    voided = service.void(
        repository, record_id, VoidRequest(version=1, reason="Entered twice"), ACTOR
    )

    assert (voided.record.status, voided.record.status_reason) == ("voided", "Entered twice")
    assert session.get(IncidentRecord, record_id) is not None
    active, _ = repository.search(RecordFilter(year=2003), limit=50, offset=0)
    assert record_id not in {r.record.id for r in active}
    every, _ = repository.search(
        RecordFilter(year=2003, statuses=("active", "voided", "reclassified")), limit=50, offset=0
    )
    assert record_id in {r.record.id for r in every}
    with pytest.raises(service.RecordRuleError, match="voided"):
        service.update(
            repository,
            record_id,
            RecordUpdate.model_validate(
                {"incidentDate": "2003-01-14", "description": "x", "version": 2}
            ),
            ACTOR,
        )


def test_reclassify_creates_the_replacement_and_links_it(
    session: Session, repository: RecordRepository
) -> None:
    original_id = create(repository, eventType="near_miss", incidentNumber="ZZT-2003-036")

    original, replacement = service.reclassify(
        repository,
        original_id,
        ReclassifyRequest(
            version=1,
            reason="Reclassified as an Incident",
            replacement=RecordFields.model_validate(
                {
                    "incidentNumber": "ZZT-2003-037",
                    "incidentDate": "2003-01-14",
                    "description": "ZZ test: reclassified event",
                }
            ),
        ),
        ACTOR,
    )

    assert (original.record.status, original.record.related_incident_id) == (
        "reclassified",
        replacement.record.id,
    )
    assert original.related_incident_number == "ZZT-2003-037"
    assert (replacement.record.event_type, replacement.record.status) == ("incident", "active")
    assert [e.action for e in audit(session, original_id)] == ["create", "update"]
    assert [e.action for e in audit(session, replacement.record.id)] == ["create"]
    counts = repository.documented_counts(2003)
    assert counts.get(("near_miss", 1), 0) == 0
    assert counts[("incident", 1)] >= 1


def test_reclassify_to_an_existing_record_needs_the_other_type(
    repository: RecordRepository,
) -> None:
    first = create(repository)
    same_type = create(repository, description="ZZ other incident")
    request = ReclassifyRequest(version=1, reason="wrong", replacement_id=same_type)

    with pytest.raises(service.RecordRuleError) as error:
        service.reclassify(repository, first, request, ACTOR)
    assert error.value.error == "invalid_replacement"


def test_history_hides_the_source_location(session: Session, repository: RecordRepository) -> None:
    created = service.create(
        repository,
        RecordCreate.model_validate(
            {"eventType": "incident", "incidentDate": "2003-01-02", "description": "ZZ import"}
        ),
        ACTOR,
        source="legacy_import",
        source_reference="mapping.json: passage 3",
    )
    [event] = repository.history(service.ENTITY_TYPE, service.entity_key(created.record.id))

    assert event.new_value is not None and event.new_value["source_reference"]
    public = service.public_audit_value(event.new_value)
    assert public is not None and "source_reference" not in public


def test_search_matches_numbers_in_any_form_and_descriptions(
    repository: RecordRepository,
) -> None:
    numbered = create(repository, incidentNumber="ZZT-2003-030")
    described = create(repository, description="ZZ test: forklift 100% clipped rack_a")

    def ids(search: str, number: str | None = None) -> set[int]:
        rows, _ = repository.search(
            RecordFilter(year=2003, search=search, search_number=number), limit=50, offset=0
        )
        return {r.record.id for r in rows}

    assert numbered in ids("ZZT 2003-30", "ZZT-2003-030")
    assert described in ids("forklift")
    assert described in ids("100%")
    assert numbered not in ids("100%")


def test_month_and_through_filters(repository: RecordRepository) -> None:
    january = create(repository, incidentDate="2003-01-20")
    march = create(repository, incidentDate="2003-03-05", eventType="near_miss")

    def ids(**criteria: Any) -> set[int]:
        rows, _ = repository.search(RecordFilter(year=2003, **criteria), limit=50, offset=0)
        return {r.record.id for r in rows}

    assert january in ids(month=1) and march not in ids(month=1)
    assert march not in ids(through_month=2) and march in ids(through_month=3)
    assert ids(event_type="near_miss") >= {march} and january not in ids(event_type="near_miss")


def test_reconciliation_compares_totals_with_active_records(
    session: Session, repository: RecordRepository
) -> None:
    metrics = DatabaseSafetyMetricsRepository(session)
    metrics.commit = session.flush  # type: ignore[method-assign]
    totals = next(s for s in metrics.sections("incidents") if s.code == "incident_near_miss_totals")
    incident = next(c.id for c in totals.categories if c.code == "incident")
    near_miss = next(c.id for c in totals.categories if c.code == "near_miss")
    metrics_service.save_changes(
        metrics,
        metric_set="incidents",
        year=2003,
        changes=[
            CellChange(category_id=incident, month=1, value=2, previous_value=None),
            CellChange(category_id=incident, month=2, value=0, previous_value=None),
            CellChange(category_id=near_miss, month=1, value=1, previous_value=None),
        ],
        actor_id="db-records-tester",
        now=NOW,
    )
    create(repository, incidentDate="2003-01-03")
    create(repository, incidentDate="2003-02-03")
    create(repository, incidentDate="2003-03-03")
    voided = create(repository, incidentDate="2003-01-04", eventType="near_miss")
    service.void(repository, voided, VoidRequest(version=1, reason="duplicate"), ACTOR)
    before = session.scalar(select(func.count()).select_from(IncidentRecord))

    result = service.reconciliation(
        repository, 2003, {"can_edit": True, "can_manage": False, "can_view_history": False}
    )

    state = {
        (m.event_type, m.month): (m.monthly_total, m.documented, m.state) for m in result.months
    }
    assert state[("incident", 1)] == (2, 1, "records_missing")
    assert state[("incident", 2)] == (0, 1, "explicit_zero_with_records")
    assert state[("incident", 3)] == (None, 1, "total_unreported_with_records")
    assert state[("incident", 4)] == (None, 0, "no_total_and_no_records")
    assert state[("near_miss", 1)] == (1, 0, "records_missing")
    # Reading never writes, and records never change the totals.
    assert session.scalar(select(func.count()).select_from(IncidentRecord)) == before
    assert metrics.values([incident], 2003)[(incident, 1)] == 2


# Narrative import ------------------------------------------------------------------


def _narrative_review() -> records_import.Review:
    """Test fixture: two reviewed 2003 passages, the second reclassifying the first."""

    def candidate(cell: str, passage: str, **parsed: Any) -> records_import.ReviewCandidate:
        return records_import.ReviewCandidate(
            candidate_id=f"Dash-{cell}-1",
            decision="include",
            recommendation="include",
            confidence="high",
            sheet="Dash",
            cell=cell,
            passage_index=1,
            passages_in_cell=1,
            original_passage=passage,
            passage_sha256=narratives.sha256_text(passage),
            parsed=records_import.ReviewParsed.model_validate(
                {
                    "reportingYear": 2003,
                    "reportingMonth": 6,
                    "description": passage,
                    "areaCode": "whse",
                    **parsed,
                }
            ),
        )

    return records_import.Review(
        source="fixture",
        workbook_sha256="0" * 64,
        extracted_at=NOW,
        candidates=[
            candidate(
                "G16",
                "ZZ fixture near miss.",
                eventType="near_miss",
                incidentNumber="ZZT-2003-036",
                incidentDate="2003-06-02",
            ),
            candidate(
                "G36",
                "ZZ fixture incident, originally reported as ZZT-2003-036.",
                eventType="incident",
                incidentNumber="ZZT-2003-037",
                incidentDate="2003-06-02",
                classificationCode="property_damage",
                reclassifiedFrom="ZZT-2003-036",
            ),
        ],
    )


def test_narrative_import_is_idempotent_and_links_reclassification(
    session: Session, repository: RecordRepository
) -> None:
    review = _narrative_review()

    created, linked = records_import.apply(repository, review, NOW)
    to_create, done, problems = records_import.plan(repository, review)

    assert (created, linked) == (2, 1)
    assert (to_create, problems) == ([], [])
    assert done == ["Dash-G16-1", "Dash-G36-1"]
    original = repository.number_owner("ZZT-2003-036")
    replacement = repository.number_owner("ZZT-2003-037")
    assert original is not None and replacement is not None
    row = repository.get(original)
    assert row is not None
    assert (row.record.status, row.record.related_incident_id) == ("reclassified", replacement)
    assert row.record.source == "legacy_import"
    assert row.record.source_reference is not None
    assert row.record.source_reference.startswith("legacy-narrative Dash!G16#1")
    assert [e.actor_id for e in audit(session, original)] == ["legacy-import", "legacy-import"]
    assert records_import.apply(repository, review, NOW) == (0, 0)


def test_narrative_plan_blocks_a_number_used_by_another_record(
    repository: RecordRepository,
) -> None:
    create(repository, incidentNumber="ZZT-2003-036")

    _, _, problems = records_import.plan(repository, _narrative_review())

    assert any("ZZT-2003-036 is already used" in p for p in problems)


# TRIR history import ---------------------------------------------------------------


def _synthetic_mapping(tmp_path: Path) -> Path:
    """Test fixture: the reviewed mapping's shape with 2001-2002 synthetic values."""
    raw = json.loads(TRIR_MAPPING.read_text(encoding="utf-8"))
    raw["source"] = "Test fixture (synthetic values)"
    raw["years"] = [
        {**raw["years"][0], "year": 2001, "note": "fixture"},
        {**raw["years"][2], "year": 2002},
    ]
    path = tmp_path / "trir_fixture.mapping.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_trir_import_applies_audits_and_is_idempotent(session: Session, tmp_path: Path) -> None:
    path = _synthetic_mapping(tmp_path)
    mapping = trir_import.load_mapping(path)
    repository = NonCommittingTrir(session)

    count, change_set = trir_import.apply_plan(
        repository, mapping, path, actor_id="db-trir-tester", now=NOW
    )
    again = trir_import.plan_import(repository.facts(), mapping)

    assert count == 2 and change_set is not None
    assert (again.inserts, again.differing, again.unchanged) == ([], [], [2001, 2002])
    stored = session.scalar(select(TrirAnnualFact).where(TrirAnnualFact.reporting_year == 2001))
    assert stored is not None
    assert (stored.recordable_count, stored.incident_count) == (1, None)
    assert str(stored.annual_man_hours) == "172301.00"
    assert stored.source_reference is not None and "H15" in stored.source_reference
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.change_set_id == change_set).order_by(AuditEvent.id)
    ).all()
    assert [e.entity_key for e in events] == ["trir-annual-facts/2001", "trir-annual-facts/2002"]
    assert trir_import.apply_plan(repository, mapping, path, actor_id="x", now=NOW) == (0, None)


@pytest.mark.empty_database
def test_reviewed_trir_mapping_applies_to_an_empty_history(session: Session) -> None:
    mapping = trir_import.load_mapping(TRIR_MAPPING)
    repository = NonCommittingTrir(session)

    count, _ = trir_import.apply_plan(
        repository, mapping, TRIR_MAPPING, actor_id="db-trir-tester", now=NOW
    )

    assert count == 6
    facts = repository.facts()
    assert str(facts[2026].legacy_displayed_trir) == "1.3774673884595783"
    assert facts[2021].incident_count is None
