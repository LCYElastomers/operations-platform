import pytest

from app.core.config import Settings


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_database_url_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", value)

    assert Settings(_env_file=None).database_url is None


def test_database_url_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:fixture-pw@localhost/db")

    settings = Settings(_env_file=None)

    assert "fixture-pw" not in repr(settings)
    assert settings.database_url is not None
    assert "fixture-pw" in settings.database_url.get_secret_value()
