"""Central TRIR case eligibility from Incident & Near Miss records.

Classification display keeps Recordable Injury, Lost Time Injury and Restricted
as separate, mutually exclusive outcomes. TRIR eligibility is broader: a unique
active record qualifies once when it carries any of those three (or Occupational
Illness, which remains a separate TRIR-qualifying classification and is not part
of the injury-outcome mutex).

Performance, TRIR Experience and related rates must use ``trir_case_counts`` /
``is_trir_recordable`` rather than summing Recordable + Lost Time + Restricted
monthly cells (which would double-count overlapping historical tags and would
follow manual cell edits that are not the TRIR authority).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.safety.models import MetricCategory, MetricSection
from app.safety.performance.calculations import Period
from app.safety.records.categories import CLASSIFICATION_SECTION, INCIDENTS_METRIC_SET
from app.safety.records.detail_models import IncidentRecordClassification
from app.safety.records.models import IncidentRecord

# Mutually exclusive injury outcomes on one record (primary + further).
INJURY_OUTCOME_CODES = frozenset(
    {"recordable_injury", "lost_time_injury", "restricted"}
)

# Codes that make an active record a TRIR case. Occupational Illness stays
# eligible and is outside the injury-outcome mutex.
TRIR_CASE_CODES = frozenset(INJURY_OUTCOME_CODES | {"occupational_illness"})

# Stored-counts key injected by the Performance repository for incident years.
TRIR_CASES_KEY = "trir_cases"


def is_trir_recordable(codes: Iterable[str]) -> bool:
    """True when the classification codes qualify the event for the TRIR numerator."""
    return bool(TRIR_CASE_CODES.intersection(codes))


def injury_outcome_codes(codes: Iterable[str]) -> frozenset[str]:
    return frozenset(INJURY_OUTCOME_CODES.intersection(codes))


def has_multiple_injury_outcomes(codes: Iterable[str]) -> bool:
    return len(injury_outcome_codes(codes)) > 1


def _classification_category_ids(session: Session, codes: Collection[str]) -> list[int]:
    if not codes:
        return []
    c, s = MetricCategory, MetricSection
    return list(
        session.scalars(
            select(c.id)
            .join(s, s.id == c.section_id)
            .where(
                s.metric_set == INCIDENTS_METRIC_SET,
                s.code == CLASSIFICATION_SECTION,
                c.code.in_(list(codes)),
            )
        )
    )


def _active_trir_records(session: Session) -> Select[tuple[int, object]]:
    """(record_id, incident_date) for active records with any TRIR-case classification."""
    ids = _classification_category_ids(session, TRIR_CASE_CODES)
    r, rc = IncidentRecord, IncidentRecordClassification
    if not ids:
        return select(r.id, r.incident_date).where(False)
    primary = select(r.id, r.incident_date).where(
        r.status == "active", r.classification_category_id.in_(ids)
    )
    further = (
        select(r.id, r.incident_date)
        .join(rc, rc.incident_record_id == r.id)
        .where(r.status == "active", rc.classification_category_id.in_(ids))
    )
    return primary.union(further)


def trir_case_counts(session: Session, years: Collection[int]) -> dict[Period, int]:
    """Distinct active TRIR-qualifying records per (year, month) for ``years``.

    Voided and superseded (reclassified) rows are excluded via ``status == active``.
    A record with several overlapping historical TRIR classifications still counts
    once.
    """
    if not years:
        return {}
    cases = _active_trir_records(session).subquery("trir_cases")
    year_expr = func.extract("year", cases.c.incident_date)
    month_expr = func.extract("month", cases.c.incident_date)
    rows = session.execute(
        select(year_expr, month_expr, func.count(func.distinct(cases.c.id)))
        .where(year_expr.in_(list(years)))
        .group_by(year_expr, month_expr)
    )
    return {(int(year), int(month)): int(count) for year, month, count in rows}


def overlapping_injury_outcome_records(session: Session) -> list[dict[str, object]]:
    """Active records that still carry more than one injury-outcome classification.

    Read-only inventory for operators; does not modify rows.
    """
    ids = _classification_category_ids(session, INJURY_OUTCOME_CODES)
    if not ids:
        return []
    r, rc, c = IncidentRecord, IncidentRecordClassification, MetricCategory
    # Primary codes.
    primary_rows = session.execute(
        select(r.id, r.incident_number, r.incident_date, c.code)
        .join(c, c.id == r.classification_category_id)
        .where(r.status == "active", r.classification_category_id.in_(ids))
    ).all()
    further_rows = session.execute(
        select(r.id, r.incident_number, r.incident_date, c.code)
        .join(rc, rc.incident_record_id == r.id)
        .join(c, c.id == rc.classification_category_id)
        .where(r.status == "active", rc.classification_category_id.in_(ids))
    ).all()
    by_record: dict[int, dict[str, object]] = {}
    for record_id, number, date, code in [*primary_rows, *further_rows]:
        entry = by_record.setdefault(
            record_id,
            {
                "recordId": record_id,
                "incidentNumber": number,
                "incidentDate": date.isoformat(),
                "outcomes": set(),
            },
        )
        cast_outcomes = entry["outcomes"]
        if isinstance(cast_outcomes, set):
            cast_outcomes.add(code)
    return [
        {
            "recordId": entry["recordId"],
            "incidentNumber": entry["incidentNumber"],
            "incidentDate": entry["incidentDate"],
            "outcomes": sorted(entry["outcomes"]) if isinstance(entry["outcomes"], set) else [],
        }
        for entry in by_record.values()
        if isinstance(entry["outcomes"], set) and len(entry["outcomes"]) > 1
    ]


def apply_trir_case_counts(
    incidents: Mapping[Period, dict[str, int]], counts: Mapping[Period, int]
) -> None:
    """Write ``trir_cases`` into each reported incident period (0 when absent)."""
    for period, stored in incidents.items():
        stored[TRIR_CASES_KEY] = counts.get(period, 0)
