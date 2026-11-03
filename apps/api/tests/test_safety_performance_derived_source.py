"""Safety Performance numerators and TRIR source boundaries."""

from app.safety.performance.calculations import INCIDENT_CATEGORIES
from app.safety.records.aggregation import DERIVED_SECTIONS, RECORD_EXPECTED_SECTIONS
from app.safety.trir_eligibility import TRIR_CASES_KEY


def test_only_totals_remain_auto_derived_monthly_sections() -> None:
    """Downstream classification / LOPC cells are manually editable again."""
    assert DERIVED_SECTIONS == ("incident_near_miss_totals",)
    assert "incident_classification" in RECORD_EXPECTED_SECTIONS
    assert "lopc" in RECORD_EXPECTED_SECTIONS


def test_incident_category_keys_still_map_to_incident_sections() -> None:
    sections = {section for section, _ in INCIDENT_CATEGORIES.values()}
    assert sections <= set(RECORD_EXPECTED_SECTIONS)
    assert INCIDENT_CATEGORIES["first_aid"] == ("incident_classification", "first_aid")
    assert INCIDENT_CATEGORIES["lopc"] == ("lopc", "lopc")
    assert INCIDENT_CATEGORIES["property_damage"] == (
        "incident_classification",
        "property_damage",
    )
    # TRIR numerator is overlaid as ``trir_cases``, not read from these cells alone.
    assert TRIR_CASES_KEY not in INCIDENT_CATEGORIES
