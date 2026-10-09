import pytest

from app.core.authorization import (
    ANONYMOUS,
    DEVELOPMENT_USER_ID,
    UserPrincipal,
    get_user_principal,
)
from app.core.config import Settings
from app.core.permissions import Permission, effective_permissions, grants

P = Permission


@pytest.mark.parametrize(
    ("granted", "required", "expected"),
    [
        (P.SAFETY_VIEW, P.SAFETY_VIEW, True),
        (P.SAFETY_VIEW, P.SAFETY_INCIDENTS_VIEW, True),
        (P.SAFETY_VIEW, P.SAFETY_INCIDENTS_EDIT, False),
        (P.SAFETY_VIEW, P.SAFETY_EDIT, False),
        (P.SAFETY_EDIT, P.SAFETY_INCIDENTS_EDIT, True),
        (P.SAFETY_EDIT, P.SAFETY_INCIDENTS_VIEW, True),
        (P.SAFETY_INCIDENTS_EDIT, P.SAFETY_INCIDENTS_VIEW, True),
        (P.SAFETY_INCIDENTS_VIEW, P.SAFETY_VIEW, False),
        (P.SAFETY_INCIDENTS_EDIT, P.SAFETY_EDIT, False),
        (P.SAFETY_VIEW, P.SAFETY_OBSERVATIONS_VIEW, True),
        (P.SAFETY_VIEW, P.SAFETY_OBSERVATIONS_EDIT, False),
        (P.SAFETY_EDIT, P.SAFETY_OBSERVATIONS_EDIT, True),
        (P.SAFETY_OBSERVATIONS_EDIT, P.SAFETY_OBSERVATIONS_VIEW, True),
        (P.SAFETY_OBSERVATIONS_VIEW, P.SAFETY_INCIDENTS_VIEW, False),
        (P.SAFETY_INCIDENTS_EDIT, P.SAFETY_OBSERVATIONS_VIEW, False),
        (P.SAFETY_INCIDENTS_VIEW, P.SAFETY_INCIDENT_RECORDS_VIEW, True),
        (P.SAFETY_INCIDENTS_EDIT, P.SAFETY_INCIDENT_RECORDS_EDIT, True),
        (P.SAFETY_INCIDENTS_EDIT, P.SAFETY_INCIDENT_RECORDS_MANAGE, False),
        (P.SAFETY_EDIT, P.SAFETY_INCIDENT_RECORDS_MANAGE, False),
        (P.SAFETY_MANAGE, P.SAFETY_INCIDENT_RECORDS_MANAGE, True),
        (P.SAFETY_MANAGE, P.SAFETY_INCIDENT_RECORDS_EDIT, True),
        (P.SAFETY_INCIDENT_RECORDS_MANAGE, P.SAFETY_INCIDENT_RECORDS_EDIT, True),
        (P.SAFETY_INCIDENT_RECORDS_MANAGE, P.SAFETY_INCIDENT_HISTORY_VIEW, False),
        (P.SAFETY_INCIDENT_RECORDS_VIEW, P.SAFETY_INCIDENT_HISTORY_VIEW, False),
        (P.SAFETY_INCIDENT_HISTORY_VIEW, P.SAFETY_INCIDENT_RECORDS_VIEW, False),
        (P.SAFETY_INCIDENT_RECORDS_EDIT, P.SAFETY_INCIDENTS_VIEW, False),
        (P.SAFETY_VIEW, P.SAFETY_TRIR_VIEW, True),
        (P.SAFETY_EDIT, P.SAFETY_TRIR_MANAGE, False),
        (P.SAFETY_TRIR_VIEW, P.SAFETY_PERFORMANCE_VIEW, False),
        (P.SAFETY_PERFORMANCE_VIEW, P.SAFETY_TRIR_VIEW, False),
        (P.SAFETY_VIEW, P.SAFETY_PERFORMANCE_VIEW, True),
        (P.SAFETY_VIEW, P.SAFETY_PERFORMANCE_EDIT, False),
        (P.SAFETY_EDIT, P.SAFETY_PERFORMANCE_EDIT, True),
        (P.SAFETY_PERFORMANCE_EDIT, P.SAFETY_PERFORMANCE_VIEW, True),
        (P.SAFETY_PERFORMANCE_EDIT, P.SAFETY_INCIDENTS_VIEW, False),
        (P.SAFETY_INCIDENTS_EDIT, P.SAFETY_PERFORMANCE_VIEW, False),
        (P.QUALITY_VIEW, P.QUALITY_COST_VIEW, True),
        (P.QUALITY_VIEW, P.QUALITY_COST_EDIT, False),
        (P.QUALITY_VIEW, P.QUALITY_COST_MANAGE, False),
        (P.QUALITY_VIEW, P.QUALITY_CARS_VIEW, True),
        (P.QUALITY_VIEW, P.QUALITY_CARS_EDIT, False),
        (P.QUALITY_CARS_EDIT, P.QUALITY_CARS_VIEW, True),
        (P.QUALITY_CARS_EDIT, P.QUALITY_COST_EDIT, False),
        (P.QUALITY_EDIT, P.QUALITY_COST_EDIT, True),
        (P.QUALITY_EDIT, P.QUALITY_COST_MANAGE, False),
        (P.QUALITY_COST_EDIT, P.QUALITY_COST_VIEW, True),
        (P.QUALITY_COST_EDIT, P.QUALITY_EDIT, False),
        (P.QUALITY_MANAGE, P.QUALITY_COST_MANAGE, True),
        (P.QUALITY_COST_VIEW, P.QUALITY_VIEW, False),
        (P.SAFETY_MANAGE, P.QUALITY_COST_VIEW, False),
        (P.QUALITY_MANAGE, P.SAFETY_VIEW, False),
    ],
)
def test_grants_follow_scope_and_action(
    granted: Permission, required: Permission, expected: bool
) -> None:
    assert grants(granted, required) is expected


def test_effective_permissions_expand_module_grants() -> None:
    assert effective_permissions([P.SAFETY_VIEW]) == {
        P.SAFETY_VIEW,
        P.SAFETY_INCIDENTS_VIEW,
        P.SAFETY_INCIDENT_RECORDS_VIEW,
        P.SAFETY_INCIDENT_HISTORY_VIEW,
        P.SAFETY_OBSERVATIONS_VIEW,
        P.SAFETY_PERFORMANCE_VIEW,
        P.SAFETY_TRIR_VIEW,
    }
    safety = {p for p in Permission if p.startswith("safety.")}
    manage_only = {P.SAFETY_MANAGE, P.SAFETY_INCIDENT_RECORDS_MANAGE, P.SAFETY_TRIR_MANAGE}
    assert effective_permissions([P.SAFETY_EDIT]) == safety - manage_only
    assert effective_permissions([P.SAFETY_MANAGE]) == safety
    assert effective_permissions([P.QUALITY_VIEW]) == {
        P.QUALITY_VIEW,
        P.QUALITY_COST_VIEW,
        P.QUALITY_CARS_VIEW,
    }
    assert effective_permissions([P.QUALITY_MANAGE]) == {
        p for p in Permission if p.startswith("quality.")
    }
    assert effective_permissions([]) == set()


def test_principal_checks_permissions_centrally() -> None:
    viewer = UserPrincipal("u", authenticated=True, granted=frozenset({P.SAFETY_INCIDENTS_VIEW}))
    assert viewer.has(P.SAFETY_INCIDENTS_VIEW)
    assert not viewer.has(P.SAFETY_INCIDENTS_EDIT)
    assert not ANONYMOUS.has(P.SAFETY_INCIDENTS_VIEW)


def test_user_auth_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USER_AUTH_MODE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.user_auth_mode == "disabled"
    assert get_user_principal(settings) is ANONYMOUS


def test_development_user_holds_configured_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER_AUTH_MODE", "development-unauthenticated")
    monkeypatch.setenv("DEVELOPMENT_USER_PERMISSIONS", '["safety.view"]')

    principal = get_user_principal(Settings(_env_file=None))

    assert principal.user_id == DEVELOPMENT_USER_ID
    assert principal.authenticated is False
    assert principal.has(P.SAFETY_INCIDENTS_VIEW)
    assert not principal.has(P.SAFETY_INCIDENTS_EDIT)


def test_development_user_defaults_to_safety_edit_and_quality_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER_AUTH_MODE", "development-unauthenticated")
    monkeypatch.delenv("DEVELOPMENT_USER_PERMISSIONS", raising=False)

    principal = get_user_principal(Settings(_env_file=None))

    assert principal.has(P.SAFETY_INCIDENTS_EDIT)
    assert principal.has(P.QUALITY_COST_VIEW)
    assert not principal.has(P.QUALITY_COST_MANAGE)


def test_unknown_development_permissions_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVELOPMENT_USER_PERMISSIONS", '["safety.admin"]')

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_development_user_mode_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "database")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:placeholder-pw@db/x")
    monkeypatch.setenv("USER_AUTH_MODE", "development-unauthenticated")

    with pytest.raises(ValueError, match="USER_AUTH_MODE=development-unauthenticated"):
        Settings(_env_file=None)


def test_dependency_fails_closed_if_production_settings_are_forced() -> None:
    settings = Settings.model_construct(
        environment="production", user_auth_mode="development-unauthenticated"
    )

    assert get_user_principal(settings) is ANONYMOUS
