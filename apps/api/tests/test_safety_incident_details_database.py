"""PostgreSQL tests for record details, Event Experience, record-derived analytics,
the detail importer and their reconciliation (migration 0017).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back; records use 2001-2004 dates and test-only
numbers (prefix ZZT), so stored data is never read or changed. The
``empty_database`` test commits through the real import commands, reads back
through a new engine and deletes what it committed.
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
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from principals import as_user
from sqlalchemy import Engine, create_engine, delete, func, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.audit.models import AuditEvent
from app.core.authorization import get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.safety import reconcile
from app.safety import router as safety_router
from app.safety.imports import runs
from app.safety.imports.models import ImportRun
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.records import detail_import, details, insights, service
from app.safety.records import legacy_import as records_import
from app.safety.records import router as records_router
from app.safety.records.detail_models import (
    IncidentDamageDetails,
    IncidentDetailCode,
    IncidentLopcDetails,
    IncidentPitDetails,
    IncidentRecordClassification,
    IncidentSeriousRiskDetails,
)
from app.safety.records.models import IncidentRecord
from app.safety.records.repository import RecordRepository
from app.safety.records.schemas import RecordCreate, RecordUpdate, VoidRequest

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 15, 17, 0, tzinfo=dt.UTC)
ACTOR = service.Actor("db-details-tester", NOW)
API_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = API_ROOT / "import_templates"
DETAILS_MAPPING = TEMPLATES / "safety_incident_details_2026_lcy_ehs.mapping.json"
RECORDS_REVIEW = TEMPLATES / "safety_incident_records_2026_lcy_ehs.review.json"
DETAIL_TABLES = (
    "incident_detail_codes",
    "incident_record_classifications",
    "incident_lopc_details",
    "incident_damage_details",
    "incident_pit_details",
    "incident_serious_risk_details",
)


def migration_0017() -> ModuleType:
    path = next((API_ROOT / "alembic" / "versions").glob("*-0017_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0017", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def class_id(repository: RecordRepository, code: str) -> int:
    return next(o.id for o in repository.classifications() if o.code == code)


def create(repository: RecordRepository, day: str = "2003-03-10", **overrides: Any) -> int:
    data: dict[str, Any] = {
        "eventType": "incident",
        "incidentDate": day,
        "description": "ZZ test event.",
        **overrides,
    }
    return service.create(repository, RecordCreate.model_validate(data), ACTOR).record.id


def classified(
    repository: RecordRepository, code: str, day: str = "2003-03-10", **extra: Any
) -> int:
    return create(repository, day, classificationCategoryId=class_id(repository, code), **extra)


def edit(repository: RecordRepository, record_id: int, **changes: Any) -> Any:
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
    return service.update(repository, record_id, RecordUpdate.model_validate(body), ACTOR)


def experience(session: Session, year: int, as_of: str, **kwargs: Any) -> dict[str, Any]:
    result = insights.event_experience(
        session, year=year, as_of=dt.date.fromisoformat(as_of), near_misses=True, **kwargs
    )
    return {c.code: c for c in result.categories}


def monthly(session: Session, section: str, code: str, year: int, month: int, value: int) -> None:
    category_id = session.scalars(
        select(MetricCategory.id)
        .join(MetricSection, MetricSection.id == MetricCategory.section_id)
        .where(
            MetricSection.metric_set == "incidents",
            MetricSection.code == section,
            MetricCategory.code == code,
        )
    ).one()
    session.execute(
        insert(MonthlyMetricValue).values(
            category_id=category_id,
            reporting_year=year,
            reporting_month=month,
            value=value,
            created_by="t",
            updated_by="t",
        )
    )


# Schema --------------------------------------------------------------------------------


def test_upgrade_creates_permanent_logged_tables_and_seeds_codes(
    session: Session, engine: Engine
) -> None:
    persistence = dict(
        session.execute(
            text(
                "SELECT c.relname, c.relpersistence FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'safety' AND c.relkind = 'r' AND c.relname = ANY(:names)"
            ),
            {"names": list(DETAIL_TABLES)},
        ).all()
    )
    assert persistence == dict.fromkeys(DETAIL_TABLES, "p")
    inspector = inspect(engine)
    for table in DETAIL_TABLES[2:]:
        foreign = inspector.get_foreign_keys(table, "safety")
        assert [(f["referred_table"], f["options"].get("ondelete")) for f in foreign] == [
            ("incident_records", "RESTRICT")
        ]
    codes = {
        (t, c)
        for t, c in session.execute(select(IncidentDetailCode.taxonomy, IncidentDetailCode.code))
    }
    for expected in (
        ("lopc_failure_mechanism", "pump_seal"),
        ("lopc_failure_mechanism", "pressure_relief_device"),
        ("secondary_containment_status", "unknown"),
        ("quantity_unit", "gallons"),
        ("damage_kind", "equipment_failure"),
        ("currency", "USD"),
        ("pit_ownership", "third_party"),
        ("potential_severity", "serious_process_safety"),
        ("serious_risk_category", "electrical_arc_flash"),
    ):
        assert expected in codes
    assert reconcile.check_detail_storage(session)[0].status == "ok"


def test_downgrade_guard_refuses_while_details_exist(
    session: Session, repository: RecordRepository
) -> None:
    create(repository, seriousRiskDetails={"isPsif": True})
    with pytest.raises(DBAPIError, match="incident record details exist"), session.begin_nested():
        session.execute(text(migration_0017().DOWNGRADE_GUARD))


def test_codes_are_stable_and_unknown_codes_are_refused(
    session: Session, repository: RecordRepository
) -> None:
    code = IncidentDetailCode
    with pytest.raises(IntegrityError, match="stable"), session.begin_nested():
        session.execute(delete(code).where(code.taxonomy == "quantity_unit", code.code == "liters"))
    with pytest.raises(IntegrityError, match="stable"), session.begin_nested():
        session.execute(
            update(code)
            .where(code.taxonomy == "quantity_unit", code.code == "liters")
            .values(code="litres")
        )
    record_id = classified(repository, "spill_release")
    with pytest.raises(IntegrityError, match="unknown"), session.begin_nested():
        session.execute(
            insert(IncidentLopcDetails).values(
                incident_record_id=record_id,
                failure_mechanism_code="zz_not_a_code",
                created_by="t",
                updated_by="t",
            )
        )
    with pytest.raises(IntegrityError, match="quantity_with_unit"), session.begin_nested():
        session.execute(
            insert(IncidentLopcDetails).values(
                incident_record_id=record_id,
                estimated_quantity=Decimal("2"),
                created_by="t",
                updated_by="t",
            )
        )
    with pytest.raises(IntegrityError, match="severity_needs_psif"), session.begin_nested():
        session.execute(
            insert(IncidentSeriousRiskDetails).values(
                incident_record_id=record_id,
                is_psif=False,
                potential_severity_code="fatality",
                created_by="t",
                updated_by="t",
            )
        )


def test_renaming_a_code_keeps_records_and_filters(
    session: Session, repository: RecordRepository
) -> None:
    record_id = classified(
        repository, "spill_release", lopcDetails={"failureMechanismCode": "pump_seal"}
    )
    session.execute(
        update(IncidentDetailCode)
        .where(IncidentDetailCode.code == "pump_seal")
        .values(name="Renamed for display")
    )
    result = insights.lopc_records(session, year=2003, through=12)
    assert [(c.key, c.name) for c in result.by_failure_mechanism] == [
        ("pump_seal", "Renamed for display")
    ]
    row = repository.get(record_id)
    assert row is not None and row.extras.details is not None
    assert row.extras.details["lopc"]["failure_mechanism_code"] == "pump_seal"


# Service: one transaction, validation, audit -------------------------------------------


def test_record_and_details_are_saved_and_audited_together(
    session: Session, repository: RecordRepository
) -> None:
    record_id = classified(
        repository,
        "spill_release",
        lopcDetails={
            "isLopc": True,
            "estimatedQuantity": "60",
            "quantityUnitCode": "gallons",
            "materialName": " cyclohexane ",
            "notes": "Confidential narrative ZZ.",
        },
    )
    row = repository.get(record_id)
    assert row is not None
    out = service.record_out(row)
    assert out.lopc_details is not None
    assert out.lopc_details.material_name == "cyclohexane"
    assert out.lopc_details.estimated_quantity == Decimal("60")
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.entity_key.like(f"incident-records/{record_id}%"))
    ).all()
    assert {(e.entity_type, e.entity_key) for e in events} == {
        ("safety.incident_record", f"incident-records/{record_id}"),
        (details.DETAIL_ENTITY_TYPE, f"incident-records/{record_id}/lopc"),
    }
    assert len({e.change_set_id for e in events}) == 1
    detail_event = next(e for e in events if e.entity_type == details.DETAIL_ENTITY_TYPE)
    assert detail_event.actor_id == ACTOR.actor_id
    assert "Confidential" not in json.dumps(detail_event.new_value)
    assert detail_event.new_value is not None
    assert detail_event.new_value["notes"].startswith("[text, 26 characters, sha256 ")


def test_a_database_failure_rolls_back_the_record_and_its_details(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = RecordRepository(session)
    before = session.scalar(select(func.count()).select_from(IncidentRecord))

    def broken(*args: Any, **kwargs: Any) -> None:
        raise IntegrityError("INSERT", {}, Exception("refused"))

    monkeypatch.setattr(repository, "save_detail", broken)
    with pytest.raises(IntegrityError):
        classified(repository, "spill_release", lopcDetails={"isLopc": True})
    assert session.scalar(select(func.count()).select_from(IncidentRecord)) == before


def test_invalid_detail_changes_nothing(session: Session, repository: RecordRepository) -> None:
    record_id = classified(repository, "first_aid")
    with pytest.raises(service.RecordRuleError) as error:
        edit(repository, record_id, description="ZZ changed", lopcDetails={"isLopc": True})
    assert (error.value.error, error.value.field) == ("detail_not_allowed", "lopcDetails")
    row = repository.get(record_id)
    assert row is not None
    assert (row.record.description, row.record.version) == ("ZZ test event.", 1)


@pytest.mark.parametrize(
    ("classification", "body", "error", "field"),
    [
        ("first_aid", {"lopcDetails": {"isLopc": True}}, "detail_not_allowed", "lopcDetails"),
        ("first_aid", {"damageDetails": {}}, "detail_not_allowed", "damageDetails"),
        (
            "property_damage",
            {"damageDetails": {"damageKindCode": "equipment_failure"}},
            "detail_not_allowed",
            "damageDetails",
        ),
        (
            "first_aid",
            {"pitDetails": {"vehicleType": "Forklift"}},
            "detail_not_allowed",
            "pitDetails",
        ),
        (
            "first_aid",
            {"seriousRiskDetails": {"isPsif": False, "potentialSeverityCode": "fatality"}},
            "severity_without_psif",
            "seriousRiskDetails.isPsif",
        ),
        (
            "spill_release",
            {"lopcDetails": {"estimatedQuantity": "2"}},
            "quantity_without_unit",
            "lopcDetails.quantityUnitCode",
        ),
        (
            "spill_release",
            {"lopcDetails": {"quantityUnitCode": "gallons"}},
            "quantity_without_unit",
            "lopcDetails.estimatedQuantity",
        ),
        (
            "property_damage",
            {"damageDetails": {"estimatedCost": "1200.50"}},
            "cost_without_currency",
            "damageDetails.currencyCode",
        ),
        (
            "spill_release",
            {"lopcDetails": {"failureMechanismCode": "zz_unknown"}},
            "invalid_code",
            "lopcDetails.failureMechanismCode",
        ),
    ],
)
def test_conditional_detail_validation(
    repository: RecordRepository, classification: str, body: dict[str, Any], error: str, field: str
) -> None:
    with pytest.raises(service.RecordRuleError) as raised:
        classified(repository, classification, **body)
    assert (raised.value.error, raised.value.field) == (error, field)


def test_qualifying_details_are_accepted(repository: RecordRepository) -> None:
    classified(
        repository,
        "pit_accident",
        additionalClassificationIds=[class_id(repository, "property_damage")],
        pitDetails={"vehicleType": "Forklift", "ownershipTypeCode": "contractor"},
        damageDetails={
            "damageKindCode": "property_damage",
            "estimatedCost": "10",
            "currencyCode": "USD",
        },
        seriousRiskDetails={"isPsif": True, "potentialSeverityCode": "life_altering"},
    )


def test_removing_a_classification_with_dependent_detail_is_refused(
    repository: RecordRepository,
) -> None:
    record_id = classified(repository, "spill_release", lopcDetails={"isLopc": True})
    with pytest.raises(service.RecordRuleError) as error:
        edit(repository, record_id, classificationCategoryId=class_id(repository, "first_aid"))
    assert error.value.error == "dependent_detail"
    assert "before removing the classification" in error.value.message
    row = repository.get(record_id)
    assert row is not None and row.extras.details is not None and "lopc" in row.extras.details

    edit(
        repository,
        record_id,
        classificationCategoryId=class_id(repository, "first_aid"),
        lopcDetails=None,
    )
    row = repository.get(record_id)
    assert row is not None and not row.extras.details
    assert row.record.version == 2


def test_a_detail_only_change_increments_the_version(repository: RecordRepository) -> None:
    record_id = classified(repository, "first_aid")
    edit(repository, record_id, seriousRiskDetails={"isPsif": True})
    edit(repository, record_id, seriousRiskDetails={"isPsif": True})
    row = repository.get(record_id)
    assert row is not None and row.record.version == 2


# Event Experience ----------------------------------------------------------------------


def test_days_since_counts_calendar_days_and_zero_on_the_as_of_date(
    session: Session, repository: RecordRepository
) -> None:
    classified(repository, "first_aid", "2003-03-01")
    at = experience(session, 2003, "2003-03-31")["first_aid"]
    assert (at.status, at.days_since_latest_event, at.ytd_events) == ("complete", 30, 1)
    assert at.latest_event is not None and at.latest_event.incident_date == dt.date(2003, 3, 1)
    same_day = experience(session, 2003, "2003-03-01")["first_aid"]
    assert same_day.days_since_latest_event == 0
    before = experience(session, 2003, "2003-02-28")["first_aid"]
    assert (before.latest_event_date, before.ytd_events) == (None, 0)


def test_year_boundary_and_an_earlier_year(session: Session, repository: RecordRepository) -> None:
    classified(repository, "first_aid", "2002-12-31")
    at = experience(session, 2003, "2003-01-01")["first_aid"]
    assert at.status == "no_event_in_scope"
    assert (at.days_since_latest_event, at.ytd_events, at.latest_in_selected_year) == (1, 0, False)
    assert "No event in 2003; the latest was on 2002-12-31." in at.warnings


def test_leap_day(session: Session, repository: RecordRepository) -> None:
    classified(repository, "fire", "2004-02-28")
    assert experience(session, 2004, "2004-03-01")["fire"].days_since_latest_event == 2


def test_no_records_is_unavailable_not_zero(session: Session) -> None:
    for category in experience(session, 2001, "2001-12-31").values():
        assert category.status == "source_unavailable"
        assert category.ytd_events_complete is False
        assert category.days_since_latest_event is None


def test_no_classified_event_is_no_event_in_scope(
    session: Session, repository: RecordRepository
) -> None:
    classified(repository, "first_aid", "2003-02-01")
    fire = experience(session, 2003, "2003-12-31")["fire"]
    assert (fire.status, fire.ytd_events, fire.ytd_events_complete) == (
        "no_event_in_scope",
        0,
        True,
    )
    assert fire.warnings == ["No classified event found."]


def test_unclassified_incident_makes_categories_incomplete(
    session: Session, repository: RecordRepository
) -> None:
    classified(repository, "first_aid", "2003-02-01")
    create(repository, "2003-08-19", incidentNumber="ZZT-2003-063")
    found = experience(session, 2003, "2003-12-31")
    recordable = found["recordable_injury"]
    assert recordable.status == "insufficient_classification_data"
    assert recordable.ytd_events_complete is False
    assert any("no classification" in w for w in recordable.warnings)
    # PSIF is a designation, not a classification.
    assert found["psif"].status != "insufficient_classification_data"


def test_monthly_count_above_records_is_incomplete(
    session: Session, repository: RecordRepository
) -> None:
    classified(repository, "first_aid", "2003-03-01")
    monthly(session, "incident_classification", "first_aid", 2003, 3, 2)
    at = experience(session, 2003, "2003-12-31")["first_aid"]
    assert (at.status, at.monthly_count, at.ytd_events) == (
        "insufficient_classification_data",
        2,
        1,
    )


def test_voided_records_are_excluded(session: Session, repository: RecordRepository) -> None:
    classified(repository, "fire", "2003-02-01")
    later = classified(repository, "fire", "2003-05-01")
    service.void(repository, later, VoidRequest(version=1, reason="ZZ duplicate"), ACTOR)
    at = experience(session, 2003, "2003-12-31")["fire"]
    assert (at.latest_event_date, at.ytd_events) == (dt.date(2003, 2, 1), 1)


def test_one_event_counts_in_each_of_its_categories(
    session: Session, repository: RecordRepository
) -> None:
    classified(
        repository,
        "pit_accident",
        "2003-04-01",
        additionalClassificationIds=[class_id(repository, "property_damage")],
        seriousRiskDetails={"isPsif": True},
    )
    classified(repository, "hazardous_condition", "2003-04-02", seriousRiskDetails={"isPsif": True})
    found = experience(session, 2003, "2003-12-31")
    assert found["pit"].ytd_events == 1
    assert found["property_damage"].ytd_events == 1
    assert found["hazardous_condition"].ytd_events == 1
    assert found["psif"].ytd_events == 2


def test_equipment_damage_and_failure_need_a_damage_kind(
    session: Session, repository: RecordRepository
) -> None:
    classified(
        repository,
        "equipment_damage_failure",
        "2003-04-01",
        damageDetails={"damageKindCode": "equipment_failure"},
    )
    found = experience(session, 2003, "2003-12-31")
    assert (found["equipment_failure"].status, found["equipment_failure"].ytd_events) == (
        "complete",
        1,
    )
    assert found["equipment_damage"].status == "no_event_in_scope"
    classified(repository, "equipment_damage_failure", "2003-04-02")
    found = experience(session, 2003, "2003-12-31")
    assert found["equipment_damage"].status == "insufficient_classification_data"
    assert found["equipment_failure"].status == "insufficient_classification_data"


def test_latest_event_uses_the_occurrence_date_and_breaks_ties_by_id(
    session: Session, repository: RecordRepository
) -> None:
    classified(repository, "fire", "2003-06-01", incidentNumber="ZZT-2003-301")
    classified(repository, "fire", "2003-06-01", incidentNumber="ZZT-2003-302")
    # Entered last but occurred first.
    classified(repository, "fire", "2003-01-05", incidentNumber="ZZT-2003-303")
    at = experience(session, 2003, "2003-12-31")["fire"]
    assert at.latest_event is not None
    assert at.latest_event.incident_number == "ZZT-2003-302"
    assert at.ytd_events == 3


# Record-derived analytics and drill-through ----------------------------------------------


def test_lopc_analytics_count_unknown_and_never_add_units(
    session: Session, repository: RecordRepository
) -> None:
    classified(
        repository,
        "spill_release",
        "2003-03-01",
        lopcDetails={
            "estimatedQuantity": "60",
            "quantityUnitCode": "gallons",
            "materialName": "Cyclohexane",
        },
    )
    classified(
        repository,
        "spill_release",
        "2003-03-02",
        lopcDetails={
            "estimatedQuantity": "2.5",
            "quantityUnitCode": "gallons",
            "materialName": "cyclohexane",
        },
    )
    classified(
        repository,
        "spill_release",
        "2003-03-03",
        lopcDetails={
            "estimatedQuantity": "40",
            "quantityUnitCode": "pounds",
            "failureMechanismCode": "pipe",
        },
    )
    classified(repository, "spill_release", "2003-03-04")
    result = insights.lopc_records(session, year=2003, through=12)
    assert (result.records, result.with_details) == (4, 3)
    assert [(q.unit_code, q.total, q.records) for q in result.quantities] == [
        ("gallons", Decimal("62.5"), 2),
        ("pounds", Decimal("40"), 1),
    ]
    assert result.records_without_quantity == 1
    assert [(c.key, c.count) for c in result.by_material] == [("cyclohexane", 2), ("unknown", 2)]
    assert [(c.key, c.count) for c in result.by_failure_mechanism] == [("pipe", 1), ("unknown", 3)]
    assert any("have no LOPC details" in w for w in result.warnings)


def test_drill_through_lists_exactly_the_counted_records(
    session: Session, repository: RecordRepository
) -> None:
    classified(
        repository, "spill_release", "2003-03-01", lopcDetails={"failureMechanismCode": "pipe"}
    )
    classified(repository, "spill_release", "2003-03-02", lopcDetails={"materialName": "NBL"})
    classified(repository, "spill_release", "2003-03-03")
    classified(
        repository,
        "pit_accident",
        "2003-03-04",
        additionalClassificationIds=[class_id(repository, "property_damage")],
    )
    app = create_app()
    app.dependency_overrides[records_router.record_repository] = lambda: repository
    app.dependency_overrides[get_user_principal] = lambda: as_user(Permission.INCIDENT_VIEW)
    client = TestClient(app)

    def total(**params: Any) -> int:
        response = client.get("/api/v1/safety/incidents/records", params={"year": 2003, **params})
        assert response.status_code == 200, response.text
        return response.json()["total"]

    assert total(category="spill_release_lopc") == 3
    assert total(failureMechanism="pipe") == 1
    assert total(category="spill_release_lopc", failureMechanism="unknown") == 2
    assert total(material="nbl") == 1
    assert total(category="property_damage") == 1
    assert total(category="pit") == 1
    assert total(classificationId=class_id(repository, "property_damage")) == 1


def test_serious_risk_analytics(session: Session, repository: RecordRepository) -> None:
    classified(
        repository,
        "hazardous_condition",
        "2003-01-21",
        seriousRiskDetails={"isPsif": True, "potentialSeverityCode": "fatality"},
    )
    create(repository, "2003-02-02", eventType="near_miss", seriousRiskDetails={"isPsif": True})
    classified(repository, "first_aid", "2003-02-03", seriousRiskDetails={"isPsif": False})
    monthly(session, "psif", "psif", 2003, 1, 2)
    result = insights.serious_risk(session, year=2003, through=2, near_misses=True)
    assert result.psif_records == 2
    assert [(m.month, m.records, m.monthly_count) for m in result.monthly] == [
        (1, 1, 2),
        (2, 1, None),
    ]
    assert [(c.name, c.count) for c in result.by_classification][-1] == ("Unclassified", 1)
    assert [(c.key, c.count) for c in result.by_severity] == [("fatality", 1), (None, 1)]
    without = insights.serious_risk(session, year=2003, through=2, near_misses=False)
    assert without.psif_records == 1


def test_event_experience_endpoint_reads_the_database(
    session: Session, repository: RecordRepository
) -> None:
    classified(repository, "first_aid", "2003-03-01", incidentNumber="ZZT-2003-401")
    app = create_app()
    app.dependency_overrides[safety_router.insight_session] = lambda: session
    app.dependency_overrides[get_user_principal] = lambda: as_user(
        Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW, Permission.INCIDENT_VIEW
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/safety/incidents/analytics/event-experience",
        params={"year": 2003, "asOf": "2003-03-31"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    first_aid = next(c for c in body["categories"] if c["code"] == "first_aid")
    assert (first_aid["daysSinceLatestEvent"], first_aid["latestEvent"]["incidentNumber"]) == (
        30,
        "ZZT-2003-401",
    )
    assert body["siteTimeZone"] == "America/Chicago"
    assert body["includesNearMisses"] is False
    assert (
        client.get(
            "/api/v1/safety/incidents/analytics/event-experience",
            params={"year": 2003, "asOf": "2004-01-01"},
        ).status_code
        == 422
    )


# Detail importer -----------------------------------------------------------------------


def _mapping(tmp_path: Path, records: list[dict[str, Any]]) -> detail_import.Mapping:
    data = {"source": "ZZ test mapping", "records": records}
    path = tmp_path / "details.mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return detail_import.load_mapping(path)


def _legacy_record(repository: RecordRepository) -> int:
    return service.create(
        repository,
        RecordCreate.model_validate(
            {
                "eventType": "incident",
                "incidentDate": "2003-01-20",
                "description": "ZZ legacy passage.",
                "classificationCategoryId": class_id(repository, "spill_release"),
            }
        ),
        ACTOR,
        source="legacy_import",
        source_reference="legacy-narrative ZZ!C29#1 sha256:0123456789abcdef",
    ).record.id


def test_import_plan_apply_and_clean_replan(
    session: Session, repository: RecordRepository, tmp_path: Path
) -> None:
    passage = _legacy_record(repository)
    numbered = classified(repository, "hazardous_condition", incidentNumber="ZZT-2003-501")
    mapping = _mapping(
        tmp_path,
        [
            {
                "legacyPassage": "ZZ!C29#1",
                "sourceQuotes": ["Three pipe leaks"],
                "lopcDetails": {
                    "failureMechanismCode": "pipe",
                    "contributingFactorCode": "mechanical_integrity",
                },
            },
            {
                "incidentNumber": "ZZT-2003-501",
                "sourceQuotes": ["(PSIF)"],
                "seriousRiskDetails": {"isPsif": True},
            },
        ],
    )
    planned = session.begin_nested()
    plan = detail_import.run_mapping(session, mapping, NOW)
    planned.rollback()
    assert (plan.inserted, plan.updated, plan.unchanged, plan.problems) == (2, 0, 0, [])
    assert repository.detail(details.LOPC, passage) is None

    plan = detail_import.run_mapping(session, mapping, NOW)
    assert (plan.inserted, plan.records_changed, plan.problems) == (2, 2, [])
    lopc = repository.detail(details.LOPC, passage)
    assert lopc is not None and lopc["failure_mechanism_code"] == "pipe"
    risk = repository.detail(details.SERIOUS_RISK, numbered)
    assert risk is not None and risk["is_psif"] is True
    events = session.scalars(
        select(AuditEvent.actor_id).where(AuditEvent.entity_type == details.DETAIL_ENTITY_TYPE)
    ).all()
    assert set(events) == {"legacy-import"}

    again = detail_import.run_mapping(session, mapping, NOW)
    assert (again.inserted, again.updated, again.unchanged, again.records_changed) == (0, 0, 2, 0)
    assert (
        reconcile.check_details_file(session, tmp_path / "details.mapping.json")[0].status == "ok"
    )


def test_import_fills_blanks_and_refuses_conflicts(
    session: Session, repository: RecordRepository, tmp_path: Path
) -> None:
    record_id = classified(
        repository,
        "spill_release",
        incidentNumber="ZZT-2003-601",
        lopcDetails={"materialName": "cyclohexane"},
    )
    fill = _mapping(
        tmp_path,
        [
            {
                "incidentNumber": "ZZT-2003-601",
                "sourceQuotes": ["approximately 60 gallons"],
                "lopcDetails": {"estimatedQuantity": "60", "quantityUnitCode": "gallons"},
            }
        ],
    )
    plan = detail_import.run_mapping(session, fill, NOW)
    assert (plan.updated, plan.problems) == (1, [])
    stored = repository.detail(details.LOPC, record_id)
    assert stored is not None
    assert (stored["material_name"], stored["estimated_quantity"]) == ("cyclohexane", Decimal("60"))

    conflict = _mapping(
        tmp_path,
        [
            {
                "incidentNumber": "ZZT-2003-601",
                "sourceQuotes": ["a different value"],
                "lopcDetails": {"materialName": "toluene"},
            }
        ],
    )
    plan = detail_import.run_mapping(session, conflict, NOW)
    assert plan.conflicts == [
        "ZZT-2003-601: lopc details material_name is 'cyclohexane'; the mapping gives 'toluene'"
    ]
    stored = repository.detail(details.LOPC, record_id)
    assert stored is not None and stored["material_name"] == "cyclohexane"


def test_import_reports_missing_references_invalid_codes_and_failures(
    session: Session, repository: RecordRepository, tmp_path: Path
) -> None:
    classified(repository, "first_aid", incidentNumber="ZZT-2003-701")
    classified(repository, "spill_release", incidentNumber="ZZT-2003-702")
    mapping = _mapping(
        tmp_path,
        [
            {
                "incidentNumber": "ZZT-2003-799",
                "sourceQuotes": ["q"],
                "seriousRiskDetails": {"isPsif": True},
            },
            {
                "incidentNumber": "ZZT-2003-702",
                "sourceQuotes": ["q"],
                "lopcDetails": {"failureMechanismCode": "zz_unknown"},
            },
            {
                "incidentNumber": "ZZT-2003-701",
                "sourceQuotes": ["q"],
                "lopcDetails": {"isLopc": True},
            },
        ],
    )
    plan = detail_import.run_mapping(session, mapping, NOW)
    assert plan.missing_references == ["ZZT-2003-799: no such record"]
    assert len(plan.invalid_codes) == 1 and "zz_unknown" in plan.invalid_codes[0]
    assert len(plan.validation_failures) == 1 and "Spill / Release" in plan.validation_failures[0]
    assert plan.records_changed == 0


# Reconciliation --------------------------------------------------------------------------


def test_reconcile_record_details_and_aggregates(
    session: Session, repository: RecordRepository
) -> None:
    classified(repository, "spill_release", "2003-03-01", incidentNumber="ZZT-2003-801")
    classified(repository, "pit_accident", "2003-03-02", pitDetails={"vehicleType": "Forklift"})
    monthly(session, "lopc", "lopc", 2003, 3, 2)
    findings = reconcile.check_record_details(session, 2003)
    missing = [f for f in findings if f.check == "detail_missing"]
    assert [f.status for f in missing] == ["warning"]
    assert "ZZT-2003-801" in missing[0].message

    aggregates = {f.check: f for f in reconcile.check_aggregates_against_records(session, 2003)}
    assert aggregates["lopc_vs_records"].status == "warning"
    assert aggregates["pit_vs_records"].status == "discrepancy"
    assert aggregates["pit_vs_records"].message == (
        "Records not counted: 2003-03 count unreported, records 1."
    )
    assert aggregates["psif_vs_records"].status == "ok"

    events = reconcile.check_event_experience(session, 2003, dt.date(2026, 10, 15))
    assert len(events) == 11
    assert all(f.check == "event_experience" for f in events)


def test_reconcile_flags_detail_without_qualifying_classification(
    session: Session, repository: RecordRepository
) -> None:
    record_id = classified(repository, "first_aid", incidentNumber="ZZT-2003-901")
    session.execute(
        insert(IncidentPitDetails).values(
            incident_record_id=record_id, vehicle_type="Forklift", created_by="t", updated_by="t"
        )
    )
    findings = reconcile.check_record_details(session, 2003)
    bad = [f for f in findings if f.check == "detail_classification"]
    assert [f.status for f in bad] == ["discrepancy"]
    assert "ZZT-2003-901" in bad[0].message


# Reviewed mapping -> PostgreSQL -> restart (disposable database only) ----------------------


@pytest.mark.empty_database
def test_reviewed_details_commit_and_survive_a_new_engine(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = sessionmaker(bind=engine)
    for module in (records_import, detail_import, runs):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)
    try:
        assert records_import.run(["apply", str(RECORDS_REVIEW)]) == 0
        assert detail_import.run(["plan", str(DETAILS_MAPPING)]) == 0
        assert detail_import.run(["apply", str(DETAILS_MAPPING)]) == 0
        assert detail_import.run(["apply", str(DETAILS_MAPPING)]) == 0
        engine.dispose()

        restarted = create_engine(engine.url)
        try:
            with Session(restarted) as fresh:
                statuses = fresh.execute(
                    select(ImportRun.command, ImportRun.status, ImportRun.inserted_count)
                    .where(ImportRun.importer == "incident_details")
                    .order_by(ImportRun.id)
                ).all()
                assert [tuple(s) for s in statuses] == [
                    ("plan", "planned", 7),
                    ("apply", "applied", 7),
                    ("apply", "nothing_to_apply", 0),
                ]
                counts = {
                    table.__tablename__: fresh.scalar(select(func.count()).select_from(table))
                    for table in (
                        IncidentLopcDetails,
                        IncidentDamageDetails,
                        IncidentSeriousRiskDetails,
                    )
                }
                assert counts == {
                    "incident_lopc_details": 3,
                    "incident_damage_details": 2,
                    "incident_serious_risk_details": 2,
                }
                found = {
                    c.code: c
                    for c in insights.event_experience(
                        fresh, year=2026, as_of=dt.date(2026, 9, 30), near_misses=True
                    ).categories
                }
                assert found["psif"].ytd_events == 2
                assert found["spill_release_lopc"].latest_event_date == dt.date(2026, 3, 30)
                assert found["spill_release_lopc"].days_since_latest_event == 184
                assert found["equipment_damage"].ytd_events == 2
                # Four 2026 incidents are unclassified, so counts are minimums.
                assert found["recordable_injury"].status == "insufficient_classification_data"
                assert [f.status for f in reconcile.check_details_file(fresh, DETAILS_MAPPING)] == [
                    "ok"
                ]
        finally:
            restarted.dispose()
    finally:
        with engine.begin() as connection:
            for table in (
                IncidentLopcDetails,
                IncidentDamageDetails,
                IncidentPitDetails,
                IncidentSeriousRiskDetails,
                IncidentRecordClassification,
            ):
                connection.execute(delete(table))
            connection.execute(
                delete(AuditEvent).where(
                    AuditEvent.entity_type.in_(
                        ("safety.incident_record", details.DETAIL_ENTITY_TYPE)
                    )
                )
            )
            connection.execute(
                delete(IncidentRecord).where(IncidentRecord.related_incident_id.is_not(None))
            )
            connection.execute(delete(IncidentRecord))
            connection.execute(delete(ImportRun))
