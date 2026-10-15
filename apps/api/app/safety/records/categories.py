"""Record categories shared by Event Experience, the record analytics and the
Incident Register filters, so a drill-through lists exactly the events counted.

A record's classifications are its ``classification_category_id`` and its
further classifications (``incident_record_classifications``), matched by
stable code; a record may be in several categories. PSIF is the record's
serious-risk designation, independent of its classifications.
"""

from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, exists, or_, select

from app.safety.models import MetricCategory, MetricSection
from app.safety.records.detail_models import (
    IncidentDamageDetails,
    IncidentLopcDetails,
    IncidentRecordClassification,
    IncidentSeriousRiskDetails,
)
from app.safety.records.models import IncidentRecord

INCIDENTS_METRIC_SET = "incidents"
CLASSIFICATION_SECTION = "incident_classification"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExperienceCategory:
    code: str
    name: str
    # Incident Classification code; None for PSIF.
    classification: str | None
    damage_kind: str | None = None
    # The stored monthly count compared with the records: (section, category).
    aggregate: tuple[str, str] | None = None

    @property
    def psif(self) -> bool:
        return self.classification is None


def _category(
    code: str, name: str, classification: str | None, damage_kind: str | None = None
) -> ExperienceCategory:
    aggregate = (
        ("psif", "psif") if classification is None else (CLASSIFICATION_SECTION, classification)
    )
    return ExperienceCategory(code, name, classification, damage_kind, aggregate)


EXPERIENCE_CATEGORIES: tuple[ExperienceCategory, ...] = (
    _category("recordable_injury", "Recordable Injury", "recordable_injury"),
    _category("first_aid", "First Aid", "first_aid"),
    _category("lost_time_injury", "Lost Time Injury", "lost_time_injury"),
    _category("spill_release_lopc", "Spill / Release / LOPC", "spill_release"),
    _category(
        "equipment_damage", "Equipment Damage", "equipment_damage_failure", "equipment_damage"
    ),
    _category(
        "equipment_failure", "Equipment Failure", "equipment_damage_failure", "equipment_failure"
    ),
    _category("property_damage", "Property Damage", "property_damage"),
    _category("pit", "Powered Industrial Vehicle Accident", "pit_accident"),
    _category("fire", "Fire", "fire"),
    _category("hazardous_condition", "Hazardous Condition", "hazardous_condition"),
    _category("psif", "PSIF", None),
)
BY_CODE = {category.code: category for category in EXPERIENCE_CATEGORIES}


def classification_ids(code: str):  # noqa: ANN201 - a SQL subquery
    c, s = MetricCategory, MetricSection
    return (
        select(c.id)
        .join(s, s.id == c.section_id)
        .where(
            s.metric_set == INCIDENTS_METRIC_SET, s.code == CLASSIFICATION_SECTION, c.code == code
        )
        .scalar_subquery()
    )


def has_classification_id(category_id: int) -> ColumnElement[bool]:
    r, rc = IncidentRecord, IncidentRecordClassification
    return or_(
        r.classification_category_id == category_id,
        exists().where(rc.incident_record_id == r.id, rc.classification_category_id == category_id),
    )


def has_classification(code: str) -> ColumnElement[bool]:
    r, rc = IncidentRecord, IncidentRecordClassification
    return or_(
        r.classification_category_id.in_(classification_ids(code)),
        exists().where(
            rc.incident_record_id == r.id,
            rc.classification_category_id.in_(classification_ids(code)),
        ),
    )


def is_classified() -> ColumnElement[bool]:
    r, rc = IncidentRecord, IncidentRecordClassification
    return or_(
        r.classification_category_id.is_not(None),
        exists().where(rc.incident_record_id == r.id),
    )


def is_psif() -> ColumnElement[bool]:
    d = IncidentSeriousRiskDetails
    return exists().where(d.incident_record_id == IncidentRecord.id, d.is_psif.is_(True))


def in_category(category: ExperienceCategory) -> ColumnElement[bool]:
    """Records of the category, of any event type and status."""
    if category.psif:
        return is_psif()
    assert category.classification is not None  # noqa: S101 - not PSIF
    condition = has_classification(category.classification)
    if category.damage_kind is not None:
        d = IncidentDamageDetails
        condition = and_(
            condition,
            exists().where(
                d.incident_record_id == IncidentRecord.id,
                d.damage_kind_code == category.damage_kind,
            ),
        )
    return and_(IncidentRecord.event_type == "incident", condition)


def damage_kind_missing() -> ColumnElement[bool]:
    """Equipment Damage / Failure records whose damage kind is not recorded."""
    d = IncidentDamageDetails
    return and_(
        has_classification("equipment_damage_failure"),
        ~exists().where(d.incident_record_id == IncidentRecord.id, d.damage_kind_code.is_not(None)),
    )


def lopc_field(column: str, value: str) -> ColumnElement[bool]:
    """Records whose LOPC detail ``column`` is ``value``; ``unknown`` matches no
    detail or a field not recorded. Text fields match case-insensitively."""
    d = IncidentLopcDetails
    field = getattr(d, column)
    if value == UNKNOWN:
        return ~exists().where(d.incident_record_id == IncidentRecord.id, field.is_not(None))
    if column in ("material_name", "equipment_tag"):
        matches = field.ilike(
            value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"), escape="\\"
        )
    elif column == "process_safety_incident":
        matches = field.is_(value == "yes")
    else:
        matches = field == value
    return exists().where(d.incident_record_id == IncidentRecord.id, matches)
