import pytest

from app.core.config import Settings


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_database_url_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", value)

    assert Settings(_env_file=None).database_url is None


def test_moisture_source_defaults_to_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOISTURE_DATA_SOURCE", raising=False)

    assert Settings(_env_file=None).moisture_data_source == "fixture"


def test_database_moisture_source_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "database")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="requires DATABASE_URL"):
        Settings(_env_file=None)


def test_fixture_moisture_source_is_refused_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("MOISTURE_DATA_SOURCE", raising=False)

    with pytest.raises(ValueError, match="MOISTURE_DATA_SOURCE=fixture is not allowed"):
        Settings(_env_file=None)


def test_production_reads_moisture_from_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "database")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:placeholder-pw@db/x")

    settings = Settings(_env_file=None)

    assert settings.moisture_data_source == "database"


@pytest.mark.parametrize("environment", ["development", "test"])
def test_fixture_remains_available_outside_production(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "fixture")

    assert Settings(_env_file=None).moisture_data_source == "fixture"


def test_unknown_moisture_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "access")

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_settings_errors_do_not_echo_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:hunter2-placeholder@db/x")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "database")
    monkeypatch.setenv("INGESTION_AUTH_MODE", "development-unauthenticated")

    with pytest.raises(ValueError) as error:
        Settings(_env_file=None)

    assert "not allowed in production" in str(error.value)
    assert "hunter2-placeholder" not in str(error.value)


def test_database_url_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:fixture-pw@localhost/db")

    settings = Settings(_env_file=None)

    assert "fixture-pw" not in repr(settings)
    assert settings.database_url is not None
    assert "fixture-pw" in settings.database_url.get_secret_value()
