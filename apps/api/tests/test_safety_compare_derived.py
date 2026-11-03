"""Unit tests for the read-only cutover comparison (no database writes)."""

import pytest

from app.safety.records.compare_derived import CellDifference, main


def test_compare_derived_rejects_an_invalid_month() -> None:
    assert main(["--year", "2026", "--month", "13"]) == 2


def test_compare_derived_requires_database_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.session import DatabaseNotConfiguredError

    monkeypatch.setattr(
        "app.safety.records.compare_derived.get_sessionmaker",
        lambda: (_ for _ in ()).throw(DatabaseNotConfiguredError("DATABASE_URL is not set")),
    )
    assert main(["--year", "2026"]) == 2


def test_cell_difference_shape() -> None:
    item = CellDifference(
        section="incident_near_miss_totals",
        category="incident",
        year=2026,
        month=10,
        stored=5,
        derived=3,
        difference=-2,
        records=["ZZT-2026-001 (incident)"],
    )
    assert item.difference == item.derived - (item.stored or 0)
