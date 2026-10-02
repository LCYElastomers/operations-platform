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


def test_unknown_moisture_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "access")

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_database_url_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:fixture-pw@localhost/db")

    settings = Settings(_env_file=None)

    assert "fixture-pw" not in repr(settings)
    assert settings.database_url is not None
    assert "fixture-pw" in settings.database_url.get_secret_value()
