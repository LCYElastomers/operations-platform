"""Safety Performance numerators read the same rebuilt monthly metric values."""

from app.safety.performance.calculations import INCIDENT_CATEGORIES
from app.safety.records.aggregation import DERIVED_SECTIONS


def test_performance_numerators_come_from_derived_incident_sections() -> None:
    sections = {section for section, _ in INCIDENT_CATEGORIES.values()}
    assert sections <= set(DERIVED_SECTIONS)
    assert INCIDENT_CATEGORIES["first_aid"] == ("incident_classification", "first_aid")
    assert INCIDENT_CATEGORIES["lopc"] == ("lopc", "lopc")
    assert INCIDENT_CATEGORIES["property_damage"] == (
        "incident_classification",
        "property_damage",
    )
