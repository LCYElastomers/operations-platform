"""Record-level tags: Injury Cause, Body Part and event cause (migration 0019).

A tag is an existing ``metric_categories`` row of the tag's section; no new
codes are created. Injury causes and body parts belong to First Aid records: a
First Aid record needs at least one of each, and a record that is not First
Aid carries neither (they are cleared when First Aid is removed). Event causes
are optional (none, one or several) on Incidents and Near Misses alike.

Each change is audited as ``safety.incident_record_detail`` with key
``incident-records/<id>/<kind>`` and the value ``{"category_ids": [...]}``.
"""

from dataclasses import dataclass

from app.safety.records.detail_models import (
    IncidentRecordBodyPart,
    IncidentRecordEventCause,
    IncidentRecordInjuryCause,
)


@dataclass(frozen=True)
class TagSpec:
    kind: str
    # Request/response field, e.g. "injury_cause_category_ids".
    field: str
    label: str
    # The Incident & Near Miss section the categories come from.
    section: str
    model: type
    # The model's category column.
    column: str
    first_aid_only: bool

    @property
    def wire_field(self) -> str:
        head, *rest = self.field.split("_")
        return head + "".join(part.title() for part in rest)


INJURY_CAUSES = TagSpec(
    kind="injury_causes",
    field="injury_cause_category_ids",
    label="Injury Cause",
    section="injury_cause",
    model=IncidentRecordInjuryCause,
    column="injury_cause_category_id",
    first_aid_only=True,
)
BODY_PARTS = TagSpec(
    kind="body_parts",
    field="body_part_category_ids",
    label="Body Part",
    section="body_part",
    model=IncidentRecordBodyPart,
    column="body_part_category_id",
    first_aid_only=True,
)
EVENT_CAUSES = TagSpec(
    kind="event_causes",
    field="event_cause_category_ids",
    label="Event Cause",
    section="near_miss_cause",
    model=IncidentRecordEventCause,
    column="event_cause_category_id",
    first_aid_only=False,
)
TAGS = (INJURY_CAUSES, BODY_PARTS, EVENT_CAUSES)
BY_KIND = {tag.kind: tag for tag in TAGS}


def audit_value(category_ids: list[int]) -> dict[str, list[int]]:
    return {"category_ids": sorted(category_ids)}
