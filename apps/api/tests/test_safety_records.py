"""Incident and Near Miss records without a database: number normalization,
reconciliation states, request validation and permissions.
(Database behaviour: test_safety_records_database.py.)"""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.safety.records import router as records_router
from app.safety.records.numbers import InvalidIncidentNumberError, normalize_incident_number
from app.safety.records.schemas import ReclassifyRequest, RecordCreate
from app.safety.records.service import reconciliation_state

P = Permission
URL = "/api/v1/safety/incidents/records"


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("LCY-2026-037", "LCY-2026-037"),
        ("LCY 2026-040", "LCY-2026-040"),
        ("LCY-2026-30", "LCY-2026-030"),
        ("lcy-2026-37", "LCY-2026-037"),
        ("  LCY - 2026 - 7 ", "LCY-2026-007"),
        ("LCY2026-1234", "LCY-2026-1234"),
        ("LCY_2026_005", "LCY-2026-005"),
    ],
)
def test_incident_numbers_are_normalized(raw: str, normalized: str) -> None:
    assert normalize_incident_number(raw) == normalized


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_number_is_no_number(raw: str | None) -> None:
    assert normalize_incident_number(raw) is None


@pytest.mark.parametrize("raw", ["2026-037", "LCY-26-037", "LCY-2026", "INC#5", "LCY-2026-0371234"])
def test_unrecognized_numbers_are_rejected_not_guessed(raw: str) -> None:
    with pytest.raises(InvalidIncidentNumberError, match="LCY-2026-037"):
        normalize_incident_number(raw)


@pytest.mark.parametrize(
    ("total", "documented", "state"),
    [
        (3, 3, "reconciled"),
        (0, 0, "reconciled"),
        (3, 1, "records_missing"),
        (1, 3, "records_exceed_total"),
        (None, 2, "total_unreported_with_records"),
        (0, 1, "explicit_zero_with_records"),
        (None, 0, "no_total_and_no_records"),
    ],
)
def test_reconciliation_states(total: int | None, documented: int, state: str) -> None:
    assert reconciliation_state(total, documented) == state


def test_explicit_zero_is_not_unreported() -> None:
    assert reconciliation_state(0, 0) != reconciliation_state(None, 0)


def _create(**overrides: Any) -> dict[str, Any]:
    return {
        "eventType": "incident",
        "incidentDate": "2026-01-14",
        "description": "Operator slipped on wet grating.",
        **overrides,
    }


def test_month_context_is_given_whole() -> None:
    with pytest.raises(ValidationError, match="together"):
        RecordCreate.model_validate(_create(reportingYear=2026))
    RecordCreate.model_validate(_create(reportingYear=2026, reportingMonth=1))


def test_event_type_must_be_known() -> None:
    with pytest.raises(ValidationError):
        RecordCreate.model_validate(_create(eventType="injury"))


def test_reclassify_needs_exactly_one_replacement() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ReclassifyRequest.model_validate({"version": 1, "reason": "wrong type"})
    with pytest.raises(ValidationError, match="exactly one"):
        ReclassifyRequest.model_validate(
            {
                "version": 1,
                "reason": "wrong type",
                "replacementId": 4,
                "replacement": {"incidentDate": "2026-01-01", "description": "x"},
            }
        )


class _UnusedRepository:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"repository.{name} used by a refused request")


@pytest.fixture
def client_for() -> Callable[..., TestClient]:
    def make(*permissions: Permission) -> TestClient:
        app = create_app()
        app.dependency_overrides[records_router.record_repository] = _UnusedRepository
        app.dependency_overrides[get_user_principal] = lambda: UserPrincipal(
            "tester", authenticated=True, granted=frozenset(permissions)
        )
        return TestClient(app)

    return make


VOID = {"version": 1, "reason": "Entered twice"}
RECLASSIFY = {"version": 1, "reason": "Was a near miss", "replacementId": 2}


@pytest.mark.parametrize(
    ("method", "path", "body", "allowed"),
    [
        ("get", "", None, P.SAFETY_INCIDENT_RECORDS_VIEW),
        ("get", "/reconciliation?year=2026", None, P.SAFETY_INCIDENT_RECORDS_VIEW),
        ("post", "", _create(), P.SAFETY_INCIDENT_RECORDS_EDIT),
        ("put", "/1", {**_create(), "version": 1}, P.SAFETY_INCIDENT_RECORDS_EDIT),
        ("post", "/1/void", VOID, P.SAFETY_INCIDENT_RECORDS_MANAGE),
        ("post", "/1/reclassify", RECLASSIFY, P.SAFETY_INCIDENT_RECORDS_MANAGE),
        ("get", "/1/history", None, P.SAFETY_INCIDENT_HISTORY_VIEW),
    ],
)
def test_each_action_needs_its_permission(
    client_for: Callable[..., TestClient],
    method: str,
    path: str,
    body: dict[str, Any] | None,
    allowed: Permission,
) -> None:
    weaker = {
        P.SAFETY_INCIDENT_RECORDS_VIEW: (P.SAFETY_PERFORMANCE_EDIT, P.SAFETY_TRIR_VIEW),
        P.SAFETY_INCIDENT_RECORDS_EDIT: (P.SAFETY_INCIDENT_RECORDS_VIEW, P.SAFETY_VIEW),
        P.SAFETY_INCIDENT_RECORDS_MANAGE: (P.SAFETY_INCIDENT_RECORDS_EDIT, P.SAFETY_EDIT),
        P.SAFETY_INCIDENT_HISTORY_VIEW: (P.SAFETY_INCIDENT_RECORDS_MANAGE,),
    }[allowed]
    for permissions in [(), weaker]:
        client = client_for(*permissions)
        response = client.request(method, URL + path, json=body)
        assert response.status_code == 403, (permissions, response.text)


def test_month_filters_need_a_year(client_for: Callable[..., TestClient]) -> None:
    response = client_for(P.SAFETY_INCIDENT_RECORDS_VIEW).get(URL, params={"month": 3})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "year_required"


def test_missing_database_is_a_503() -> None:
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: UserPrincipal(
        "tester", authenticated=True, granted=frozenset({P.SAFETY_INCIDENT_RECORDS_VIEW})
    )
    with TestClient(app) as client:
        assert client.get(URL).status_code == 503
