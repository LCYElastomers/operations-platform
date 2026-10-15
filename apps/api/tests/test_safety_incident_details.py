"""Record details, Event Experience and record analytics without a database:
request validation, detail rules, audit values, endpoint permissions, the site
calendar and database failures. (Database behaviour:
test_safety_incident_details_database.py.)"""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from principals import as_user
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.authorization import get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.safety import router as safety_router
from app.safety.records import categories, details
from app.safety.records.schemas import LopcDetails, RecordCreate, SeriousRiskDetails

P = Permission
DASHBOARD = (P.SAFETY_RECORD_VIEW, P.SAFETY_DASHBOARD_VIEW)
BASE = "/api/v1/safety/incidents/analytics"
CODES = {"quantity_unit": {"gallons"}, "lopc_failure_mechanism": {"pipe", "old"}}
ACTIVE = {"quantity_unit": {"gallons"}, "lopc_failure_mechanism": {"pipe"}}


def _lopc(**values: Any) -> dict[str, Any]:
    return details.normalized(details.LOPC, LopcDetails.model_validate(values))


# Requests and rules ----------------------------------------------------------------------


def test_detail_objects_reject_unknown_fields_and_negative_quantities() -> None:
    with pytest.raises(ValidationError):
        LopcDetails.model_validate({"isLopc": True, "volume": 3})
    with pytest.raises(ValidationError):
        LopcDetails.model_validate({"estimatedQuantity": "-1", "quantityUnitCode": "gallons"})
    with pytest.raises(ValidationError):
        SeriousRiskDetails.model_validate({})


def test_quantities_are_exact_decimals_serialized_as_text() -> None:
    detail = LopcDetails.model_validate(
        {"estimatedQuantity": "0.50", "quantityUnitCode": "gallons"}
    )
    assert detail.estimated_quantity == Decimal("0.50")
    assert detail.model_dump(mode="json", by_alias=True)["estimatedQuantity"] == "0.5"


def test_omitted_null_and_given_details_are_distinct() -> None:
    base = {"eventType": "incident", "incidentDate": "2026-01-14", "description": "x"}
    omitted = RecordCreate.model_validate(base)
    cleared = RecordCreate.model_validate({**base, "lopcDetails": None})
    assert "lopc_details" not in omitted.model_fields_set
    assert "lopc_details" in cleared.model_fields_set and cleared.lopc_details is None


def test_blank_text_is_not_recorded_and_unknown_stays_unknown() -> None:
    values = _lopc(materialName="   ", isLopc=None)
    assert values["material_name"] is None
    assert values["is_lopc"] is None


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"estimatedQuantity": "2"}, "quantity_without_unit"),
        ({"quantityUnitCode": "gallons"}, "quantity_without_unit"),
        ({"failureMechanismCode": "nope"}, "invalid_code"),
        ({"failureMechanismCode": "old"}, "invalid_code"),
    ],
)
def test_lopc_rules(values: dict[str, Any], error: str) -> None:
    with pytest.raises(details.DetailRuleError) as raised:
        details.check_values(
            details.LOPC, _lopc(**values), known_codes=CODES, active_codes=ACTIVE, stored=None
        )
    assert raised.value.error == error


def test_an_inactive_code_stays_valid_only_when_unchanged() -> None:
    values = _lopc(failureMechanismCode="old")
    details.check_values(
        details.LOPC, values, known_codes=CODES, active_codes=ACTIVE, stored=dict(values)
    )


def test_requirements_follow_classification_codes() -> None:
    damage = {"damage_kind_code": "equipment_failure"}
    assert details.requirement_problem(details.LOPC, {}, {"spill_release"}) is None
    assert details.requirement_problem(details.LOPC, {}, {"first_aid"}) is not None
    assert details.requirement_problem(details.DAMAGE, damage, {"property_damage"}) is not None
    assert details.requirement_problem(details.DAMAGE, damage, {"equipment_damage_failure"}) is None
    assert details.requirement_problem(details.PIT, {}, {"pit_accident", "property_damage"}) is None
    assert details.requirement_problem(details.SERIOUS_RISK, {}, set()) is None


def test_audit_values_never_repeat_narrative_text() -> None:
    value = details.audit_value(
        details.LOPC,
        _lopc(notes="Confidential", estimatedQuantity="2.50", quantityUnitCode="gallons"),
    )
    assert value is not None
    assert value["notes"].startswith("[text, 12 characters, sha256 ")
    assert "Confidential" not in str(value)
    assert value["estimated_quantity"] == "2.5"


def test_eleven_event_experience_categories_with_stable_codes() -> None:
    assert [c.code for c in categories.EXPERIENCE_CATEGORIES] == [
        "recordable_injury",
        "first_aid",
        "lost_time_injury",
        "spill_release_lopc",
        "equipment_damage",
        "equipment_failure",
        "property_damage",
        "pit",
        "fire",
        "hazardous_condition",
        "psif",
    ]


# Endpoints -------------------------------------------------------------------------------


class _BrokenSession:
    def __getattr__(self, name: str) -> Any:
        def fail(*args: object, **kwargs: object) -> Any:
            raise OperationalError("SELECT", {}, Exception("server closed the connection"))

        return fail


def _client(*permissions: Permission, session: Any = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[safety_router.insight_session] = lambda: session or _BrokenSession()
    app.dependency_overrides[get_user_principal] = lambda: as_user(*permissions)
    return TestClient(app)


@pytest.mark.parametrize("path", ["event-experience", "lopc-records", "serious-risk"])
def test_a_database_failure_is_503_never_zero(path: str) -> None:
    response = _client(*DASHBOARD, P.INCIDENT_VIEW).get(f"{BASE}/{path}", params={"year": 2026})
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"


@pytest.mark.parametrize("path", ["event-experience", "lopc-records", "serious-risk"])
@pytest.mark.parametrize(
    "permissions",
    [(), (P.SAFETY_RECORD_VIEW, P.INCIDENT_VIEW), DASHBOARD, (P.NEAR_MISS_VIEW, *DASHBOARD)],
)
def test_record_analytics_need_dashboard_and_incident_view(
    path: str, permissions: tuple[Permission, ...]
) -> None:
    response = _client(*permissions).get(f"{BASE}/{path}", params={"year": 2026})
    assert response.status_code in (401, 403)


def test_missing_database_is_a_503() -> None:
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: as_user(*DASHBOARD, P.INCIDENT_VIEW)
    response = TestClient(app).get(f"{BASE}/event-experience", params={"year": 2026})
    assert response.status_code == 503


def test_as_of_defaults_to_the_site_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """03:00 UTC on 1 January is still 31 December in Baytown."""
    seen: dict[str, Any] = {}

    def capture(session: Any, *, year: int, as_of: dt.date, near_misses: bool) -> Any:
        seen.update(year=year, as_of=as_of, near_misses=near_misses)
        raise OperationalError("SELECT", {}, Exception("stop"))

    monkeypatch.setattr(safety_router.insights, "event_experience", capture)
    monkeypatch.setattr(safety_router, "_now", lambda: dt.datetime(2027, 1, 1, 3, 0, tzinfo=dt.UTC))
    client = _client(*DASHBOARD, P.INCIDENT_VIEW, P.NEAR_MISS_VIEW, session=object())
    response = client.get(f"{BASE}/event-experience", params={"year": 2027})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "year_not_started"

    client.get(f"{BASE}/event-experience", params={"year": 2026})
    assert seen == {"year": 2026, "as_of": dt.date(2026, 12, 31), "near_misses": True}
    client.get(f"{BASE}/event-experience", params={"year": 2025})
    assert seen["as_of"] == dt.date(2025, 12, 31)


@pytest.mark.parametrize("as_of", ["2025-12-31", "2026-10-16"])
def test_as_of_must_be_in_the_year_and_not_in_the_future(
    monkeypatch: pytest.MonkeyPatch, as_of: str
) -> None:
    monkeypatch.setattr(
        safety_router, "_now", lambda: dt.datetime(2026, 10, 15, 17, 0, tzinfo=dt.UTC)
    )
    response = _client(*DASHBOARD, P.INCIDENT_VIEW, session=object()).get(
        f"{BASE}/event-experience", params={"year": 2026, "asOf": as_of}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_as_of"


def test_record_analytics_refuse_a_month_that_has_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        safety_router, "_now", lambda: dt.datetime(2026, 10, 15, 17, 0, tzinfo=dt.UTC)
    )
    client = _client(*DASHBOARD, P.INCIDENT_VIEW, session=object())
    response = client.get(f"{BASE}/lopc-records", params={"year": 2026, "through": 11})
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "month_not_started",
        "message": "Analytics cannot run through a month that has not started.",
        "latestMonth": 10,
    }
