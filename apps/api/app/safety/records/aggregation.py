"""Derived monthly Incident & Near Miss values, rebuilt from the individual records.

Individual ``incident_records`` are the source of truth. After a record is
created, edited, voided or reclassified, the derived ``monthly_metric_values``
of every affected month are rebuilt from the *active* records only: voided
records and reclassified (superseded) originals are never counted, so a
reclassification's replacement is counted once.

Counting rules, per active record dated in the month:

- the record adds 1 to the Incident or Near Miss total (by event type);
- its area adds 1 to Incidents by Area or Near Misses by Area;
- its primary and each further classification add 1 to that Incident
  Classification (a classification repeated on one record counts once);
- a First Aid record (primary or further) adds 1 to each Injury Cause and each
  Body Part it carries;
- each event cause adds 1 to that Near-Miss Cause (Incidents and Near Misses);
- Spill / Release adds 1 to LOPC, and its LOPC contributing factor adds 1 to
  that LOPC Contributing Factor;
- Property Damage and/or Equipment Damage / Failure adds 1 (once per record)
  to Property / Equipment Damage;
- PIT Accident adds 1 to PIT;
- a serious-risk detail with ``is_psif`` adds 1 to PSIF.

A rebuilt month is *reported*: every derived category of the month is written,
0 where nothing counted. Behavior counts are a separate table and Near-Miss
Potential has no source on a record, so neither is touched.
"""

import datetime as dt
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import CompoundSelect, Select, delete, func, insert, select, text, union
from sqlalchemy.orm import Session, aliased

from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.records.detail_models import (
    IncidentLopcDetails,
    IncidentRecordBodyPart,
    IncidentRecordClassification,
    IncidentRecordEventCause,
    IncidentRecordInjuryCause,
    IncidentSeriousRiskDetails,
)
from app.safety.records.models import IncidentRecord

INCIDENTS_METRIC_SET = "incidents"

TOTALS = "incident_near_miss_totals"
CLASSIFICATION = "incident_classification"
LOPC = "lopc"
PROPERTY_EQUIPMENT_DAMAGE = "property_equipment_damage"
PIT = "pit"
PSIF = "psif"
INCIDENTS_BY_AREA = "incidents_by_area"
NEAR_MISSES_BY_AREA = "near_misses_by_area"
EVENT_CAUSE = "near_miss_cause"
LOPC_CONTRIBUTING_FACTOR = "lopc_contributing_factor"
INJURY_CAUSE = "injury_cause"
BODY_PART = "body_part"

# Sections whose monthly values are computed from the records and so are never typed.
# Near-Miss Potential is not here: nothing on a record feeds it. Behavior is a separate
# table (and endpoint) and is not a metric section.
DERIVED_SECTIONS = (
    TOTALS,
    CLASSIFICATION,
    LOPC,
    PROPERTY_EQUIPMENT_DAMAGE,
    PIT,
    PSIF,
    INCIDENTS_BY_AREA,
    NEAR_MISSES_BY_AREA,
    EVENT_CAUSE,
    LOPC_CONTRIBUTING_FACTOR,
    INJURY_CAUSE,
    BODY_PART,
)

FIRST_AID = "first_aid"
SPILL_RELEASE = "spill_release"
PROPERTY_DAMAGE = "property_damage"
EQUIPMENT_DAMAGE_FAILURE = "equipment_damage_failure"
PIT_ACCIDENT = "pit_accident"

# Event type -> (total category code, area section).
EVENT_TYPE_TARGETS = {
    "incident": ("incident", INCIDENTS_BY_AREA),
    "near_miss": ("near_miss", NEAR_MISSES_BY_AREA),
}

Month = tuple[int, int]


@dataclass(frozen=True)
class _Category:
    id: int
    section: str
    code: str
    area_id: int | None
    active: bool


class _Categories:
    """The categories of the derived sections, looked up by code or area."""

    def __init__(self, categories: Sequence[_Category]) -> None:
        self.all = list(categories)
        self._by_code = {(c.section, c.code): c.id for c in categories}
        self._by_area = {(c.section, c.area_id): c.id for c in categories if c.area_id}

    def code(self, section: str, code: str) -> int | None:
        return self._by_code.get((section, code))

    def area(self, section: str, area_id: int) -> int | None:
        return self._by_area.get((section, area_id))


def _load_categories(session: Session) -> _Categories:
    c, s = MetricCategory, MetricSection
    rows = session.execute(
        select(c.id, s.code, c.code, c.area_id, c.active)
        .join(s, s.id == c.section_id)
        .where(s.metric_set == INCIDENTS_METRIC_SET, s.code.in_(DERIVED_SECTIONS))
        .order_by(s.display_order, c.display_order, c.id)
    ).all()
    return _Categories([_Category(*row) for row in rows])


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    end = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    return start, end


def _classification_pairs() -> CompoundSelect:
    """(record, classification) for every primary and further classification."""
    r, rc = IncidentRecord, IncidentRecordClassification
    return union(
        select(r.id.label("record_id"), r.classification_category_id.label("category_id")).where(
            r.classification_category_id.is_not(None)
        ),
        select(rc.incident_record_id, rc.classification_category_id),
    )


def month_counts(session: Session, categories: _Categories, year: int, month: int) -> Counter[int]:
    """Derived category id -> count for the month, from its active records."""
    start, end = month_bounds(year, month)
    r = IncidentRecord
    # Never correlated to the queries that select from the records themselves.
    month_ids = (
        select(r.id)
        .where(r.status == "active", r.incident_date >= start, r.incident_date < end)
        .correlate(None)
    )
    counts: Counter[int] = Counter()

    def add(section: str, code: str, amount: int) -> None:
        category_id = categories.code(section, code)
        if category_id is not None and amount:
            counts[category_id] += amount

    # Totals and areas.
    for event_type, count in session.execute(
        select(r.event_type, func.count()).where(r.id.in_(month_ids)).group_by(r.event_type)
    ):
        total_code, _ = EVENT_TYPE_TARGETS[event_type]
        add(TOTALS, total_code, count)
    for event_type, area_id, count in session.execute(
        select(r.event_type, r.area_id, func.count())
        .where(r.id.in_(month_ids), r.area_id.is_not(None))
        .group_by(r.event_type, r.area_id)
    ):
        _, area_section = EVENT_TYPE_TARGETS[event_type]
        category_id = categories.area(area_section, area_id)
        if category_id is not None:
            counts[category_id] += count

    # Classifications: primary and further, once per record.
    pairs = _classification_pairs().subquery("classifications")
    for category_id, count in session.execute(
        select(pairs.c.category_id, func.count())
        .where(pairs.c.record_id.in_(month_ids))
        .group_by(pairs.c.category_id)
    ):
        counts[category_id] += count

    def with_classification(*codes: str) -> Select[tuple[int]]:
        """Active records of the month carrying any of the classification codes."""
        category = aliased(MetricCategory)
        return (
            select(pairs.c.record_id)
            .join(category, category.id == pairs.c.category_id)
            .where(category.code.in_(codes), pairs.c.record_id.in_(month_ids))
            .distinct()
            .correlate(None)
        )

    def number_of(records: Select[tuple[int]]) -> int:
        return session.scalar(select(func.count()).select_from(records.subquery())) or 0

    first_aid = with_classification(FIRST_AID)
    spill_release = with_classification(SPILL_RELEASE)
    add(LOPC, "lopc", number_of(spill_release))
    add(
        PROPERTY_EQUIPMENT_DAMAGE,
        "property_equipment_damage",
        number_of(with_classification(PROPERTY_DAMAGE, EQUIPMENT_DAMAGE_FAILURE)),
    )
    add(PIT, "pit", number_of(with_classification(PIT_ACCIDENT)))

    # First Aid: injury causes and body parts.
    injury, body = IncidentRecordInjuryCause, IncidentRecordBodyPart
    for category_id, count in session.execute(
        select(injury.injury_cause_category_id, func.count())
        .where(injury.incident_record_id.in_(first_aid))
        .group_by(injury.injury_cause_category_id)
    ):
        counts[category_id] += count
    for category_id, count in session.execute(
        select(body.body_part_category_id, func.count())
        .where(body.incident_record_id.in_(first_aid))
        .group_by(body.body_part_category_id)
    ):
        counts[category_id] += count

    # Event causes (Incidents and Near Misses).
    cause = IncidentRecordEventCause
    for category_id, count in session.execute(
        select(cause.event_cause_category_id, func.count())
        .where(cause.incident_record_id.in_(month_ids))
        .group_by(cause.event_cause_category_id)
    ):
        counts[category_id] += count

    # LOPC contributing factor of the Spill / Release records.
    lopc, factor, section = IncidentLopcDetails, MetricCategory, MetricSection
    for category_id, count in session.execute(
        select(factor.id, func.count())
        .select_from(lopc)
        .join(factor, factor.code == lopc.contributing_factor_code)
        .join(section, section.id == factor.section_id)
        .where(
            section.metric_set == INCIDENTS_METRIC_SET,
            section.code == LOPC_CONTRIBUTING_FACTOR,
            lopc.incident_record_id.in_(spill_release),
        )
        .group_by(factor.id)
    ):
        counts[category_id] += count

    # PSIF designations.
    risk = IncidentSeriousRiskDetails
    psif = session.scalar(
        select(func.count()).where(
            risk.is_psif.is_(True), risk.incident_record_id.in_(month_ids)
        )
    )
    add(PSIF, "psif", psif or 0)
    return counts


def _lock_year(session: Session, year: int) -> None:
    """Serialize with saves of the year's monthly values (the same lock key)."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"safety.monthly_metric_values:{INCIDENTS_METRIC_SET}:{year}"},
    )


def rebuild_months(
    session: Session, months: Iterable[Month], *, actor_id: str, at: dt.datetime
) -> None:
    """Rebuild the derived monthly values of each (year, month) from its active records.

    Runs in the caller's transaction and commits nothing: a record change and its
    totals succeed or fail together.
    """
    wanted = sorted(set(months))
    if not wanted:
        return
    for year in sorted({year for year, _ in wanted}):
        _lock_year(session, year)
    categories = _load_categories(session)
    v = MonthlyMetricValue
    derived_ids = [c.id for c in categories.all]
    for year, month in wanted:
        counts = month_counts(session, categories, year, month)
        session.execute(
            delete(v).where(
                v.reporting_year == year,
                v.reporting_month == month,
                v.category_id.in_(derived_ids),
            )
        )
        rows = [
            {
                "category_id": category.id,
                "reporting_year": year,
                "reporting_month": month,
                "value": counts.get(category.id, 0),
                "created_at": at,
                "created_by": actor_id,
                "updated_at": at,
                "updated_by": actor_id,
            }
            for category in categories.all
            if category.active or counts.get(category.id)
        ]
        if rows:
            session.execute(insert(v), rows)
