"""Record-derived Incident & Near Miss analytics: Event Experience, LOPC detail and
serious risk. Read-only; calculated from the committed active records on every
request, never from files and never stored.

Event Experience ("days since the last ...") needs actual event dates, so it
reads records only. For each category (``categories.EXPERIENCE_CATEGORIES``):

- Scope: active records (voided and reclassified excluded) dated on or before
  the as-of date. The year to date is 1 January of the selected year to the
  as-of date. PSIF counts incidents and, when the user may view them, near
  misses; every other category counts incidents.
- The latest event is the latest ``incident_date`` (never created/updated
  time) on or before the as-of date, in any year; ties go to the higher record
  id. Days since = as-of date - that date, in calendar days.
- Status, first that applies:
  ``source_unavailable``: no record of the category's event types exists on or
  before the as-of date.
  ``insufficient_classification_data``: an incident in the year to date has no
  classification (not PSIF); an Equipment Damage / Failure record has no damage
  kind (Equipment Damage and Equipment Failure); or the stored monthly count
  for the year to date exceeds the classified records.
  ``complete``: at least one event in the year to date.
  ``no_event_in_scope``: none in the year to date.

The LOPC and serious-risk views are labelled record-derived: the stored monthly
LOPC and PSIF totals stay authoritative and are shown beside them.
"""

import datetime as dt
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.safety.models import Area, MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.records import categories
from app.safety.records.categories import UNKNOWN, ExperienceCategory
from app.safety.records.detail_models import (
    IncidentLopcDetails,
    IncidentRecordClassification,
    IncidentSeriousRiskDetails,
)
from app.safety.records.details import LOPC_CONTRIBUTING_FACTOR
from app.safety.records.models import IncidentRecord
from app.safety.records.repository import RecordRepository
from app.safety.records.schemas import (
    CountOut,
    EventExperienceResponse,
    EventSummaryOut,
    ExperienceCategoryOut,
    LopcRecordsResponse,
    MonthCountOut,
    QuantityOut,
    SeriousRiskResponse,
)
from app.safety.site_calendar import SITE_TIME_ZONE

SUMMARY_LENGTH = 280
RECENT = 10
NOT_RECORDED = "Unknown / not recorded"


def _summaries(session: Session, record_ids: Sequence[int]) -> list[EventSummaryOut]:
    """Event summaries in the order of ``record_ids``."""
    if not record_ids:
        return []
    r, c, rc = IncidentRecord, MetricCategory, IncidentRecordClassification
    rows = {
        row.id: row
        for row in session.execute(
            select(
                r.id,
                r.incident_number,
                r.event_type,
                r.incident_date,
                r.area_id,
                r.description,
                Area.name.label("area_name"),
                c.name.label("primary"),
            )
            .outerjoin(Area, Area.id == r.area_id)
            .outerjoin(c, c.id == r.classification_category_id)
            .where(r.id.in_(record_ids))
        ).all()
    }
    further: dict[int, list[str]] = {}
    for record_id, name in session.execute(
        select(rc.incident_record_id, c.name)
        .join(c, c.id == rc.classification_category_id)
        .where(rc.incident_record_id.in_(record_ids))
        .order_by(c.display_order, c.id)
    ).all():
        further.setdefault(record_id, []).append(name)
    out = []
    for record_id in record_ids:
        row = rows[record_id]
        text = row.description
        if len(text) > SUMMARY_LENGTH:
            text = text[: SUMMARY_LENGTH - 1].rstrip() + "…"
        out.append(
            EventSummaryOut(
                id=row.id,
                incident_number=row.incident_number,
                event_type=row.event_type,
                incident_date=row.incident_date,
                area_id=row.area_id,
                area_name=row.area_name,
                classifications=[n for n in (row.primary, *further.get(record_id, ())) if n],
                description=text,
            )
        )
    return out


def _monthly_count(
    session: Session, year: int, months: int, key: tuple[str, str]
) -> tuple[int | None, bool]:
    """The stored monthly count summed over January..``months`` (None when no
    month is reported) and whether every one of those months is reported."""
    if months < 1:
        return None, False
    v, c, s = MonthlyMetricValue, MetricCategory, MetricSection
    values = session.scalars(
        select(v.value)
        .join(c, c.id == v.category_id)
        .join(s, s.id == c.section_id)
        .where(
            s.metric_set == categories.INCIDENTS_METRIC_SET,
            s.code == key[0],
            c.code == key[1],
            v.reporting_year == year,
            v.reporting_month <= months,
        )
    ).all()
    return (sum(values) if values else None), len(values) == months


def _count(session: Session, *conditions: ColumnElement[bool]) -> int:
    return session.scalar(select(func.count()).select_from(IncidentRecord).where(*conditions)) or 0


# Event Experience ------------------------------------------------------------------------


def _event_types(category: ExperienceCategory, near_misses: bool) -> tuple[str, ...]:
    return ("incident", "near_miss") if category.psif and near_misses else ("incident",)


def event_experience(
    session: Session, *, year: int, as_of: dt.date, near_misses: bool
) -> EventExperienceResponse:
    r = IncidentRecord
    active = r.status == "active"
    start = dt.date(year, 1, 1)
    in_window = and_(r.incident_date >= start, r.incident_date <= as_of)
    unclassified = _count(
        session, active, r.event_type == "incident", in_window, ~categories.is_classified()
    )
    kind_missing = _count(
        session, active, r.event_type == "incident", in_window, categories.damage_kind_missing()
    )
    out = []
    for category in categories.EXPERIENCE_CATEGORIES:
        types = r.event_type.in_(_event_types(category, near_misses))
        matches = and_(active, types, categories.in_category(category))
        ytd = _count(session, matches, in_window)
        latest = session.execute(
            select(r.id, r.incident_date)
            .where(matches, r.incident_date <= as_of)
            .order_by(r.incident_date.desc(), r.id.desc())
            .limit(1)
        ).first()
        available = _count(session, active, types, r.incident_date <= as_of) > 0
        assert category.aggregate is not None  # noqa: S101 - every category has one
        monthly, _ = _monthly_count(session, year, as_of.month, category.aggregate)
        # Records counted by the monthly count: Equipment Damage and Equipment
        # Failure share the Equipment Damage / Failure count.
        counted = (
            categories.is_psif()
            if category.psif
            else and_(
                r.event_type == "incident", categories.has_classification(category.classification)
            )
        )
        classified = _count(session, active, types, in_window, counted)

        warnings: list[str] = []
        insufficient = False
        if not category.psif and unclassified:
            insufficient = True
            warnings.append(
                f"{unclassified} incident {'record has' if unclassified == 1 else 'records have'} "
                f"no classification in {year} and may belong here."
            )
        if category.damage_kind is not None and kind_missing:
            insufficient = True
            warnings.append(
                f"{kind_missing} Equipment Damage / Failure "
                f"{'record does' if kind_missing == 1 else 'records do'} not say whether it was "
                "damage or a failure."
            )
        if monthly is not None and monthly > classified:
            insufficient = True
            warnings.append(
                f"The monthly count for {year} is {monthly}; {classified} "
                f"{'record is' if classified == 1 else 'records are'} classified."
            )
        if not available:
            status = "source_unavailable"
            warnings = ["No Incident Register records are stored for this scope."]
        elif insufficient:
            status = "insufficient_classification_data"
        elif ytd:
            status = "complete"
        else:
            status = "no_event_in_scope"
        latest_date = latest.incident_date if latest else None
        if available and not ytd:
            warnings.append(
                f"No event in {year}; the latest was on {latest_date.isoformat()}."
                if latest_date
                else "No classified event found."
            )
        out.append(
            ExperienceCategoryOut(
                code=category.code,
                name=category.name,
                year=year,
                as_of=as_of,
                status=status,  # type: ignore[arg-type]
                latest_event_date=latest_date,
                days_since_latest_event=(as_of - latest_date).days if latest_date else None,
                latest_in_selected_year=latest_date is not None and latest_date.year == year,
                ytd_events=ytd,
                ytd_events_complete=status in ("complete", "no_event_in_scope"),
                latest_event=_summaries(session, [latest.id])[0] if latest else None,
                monthly_count=monthly,
                warnings=warnings,
            )
        )
    return EventExperienceResponse(
        year=year,
        as_of=as_of,
        site_time_zone=SITE_TIME_ZONE.key,
        includes_near_misses=near_misses,
        categories=out,
    )


# Record analytics --------------------------------------------------------------------------


def _window(year: int, through: int | None) -> ColumnElement[bool]:
    r = IncidentRecord
    if through is None:
        return r.id.is_(None)
    end = dt.date(year + 1, 1, 1) if through == 12 else dt.date(year, through + 1, 1)
    return and_(r.incident_date >= dt.date(year, 1, 1), r.incident_date < end)


def _counts(
    values: Sequence[str | None],
    name: Callable[[str], str],
    *,
    unknown_key: str | None = UNKNOWN,
) -> list[CountOut]:
    """Counts per value, highest first; not recorded last."""
    tally = Counter(values)
    known = sorted(((k, n) for k, n in tally.items() if k is not None), key=lambda i: (-i[1], i[0]))
    out = [CountOut(key=key, name=name(key), count=n) for key, n in known]
    if tally.get(None):
        out.append(CountOut(key=unknown_key, name=NOT_RECORDED, count=tally[None]))
    return out


def _names(session: Session) -> dict[str, dict[str, str]]:
    return {
        taxonomy.removeprefix("metric:"): {code: name for code, name, _ in entries}
        for taxonomy, entries in RecordRepository(session).detail_codes().items()
    }


def lopc_records(session: Session, *, year: int, through: int | None) -> LopcRecordsResponse:
    r, d = IncidentRecord, IncidentLopcDetails
    category = categories.BY_CODE["spill_release_lopc"]
    rows = session.execute(
        select(
            r.id,
            r.incident_date,
            d.id.label("detail_id"),
            d.material_name,
            d.equipment_tag,
            d.estimated_quantity,
            d.quantity_unit_code,
            d.failure_mechanism_code,
            d.secondary_containment_status_code,
            d.process_safety_incident,
        )
        .outerjoin(d, d.incident_record_id == r.id)
        .where(r.status == "active", categories.in_category(category), _window(year, through))
        .order_by(r.incident_date.desc(), r.id.desc())
    ).all()
    names = _names(session)

    def named(taxonomy: str) -> Callable[[str], str]:
        return lambda code: names.get(taxonomy, {}).get(code, code)

    def text_counts(values: Sequence[str | None]) -> list[CountOut]:
        # Grouped case-insensitively (as the Register filter matches), shown as most
        # recently written.
        first: dict[str, str] = {}
        keys = [
            None if value is None else first.setdefault(value.casefold(), value) for value in values
        ]
        return _counts(keys, lambda key: key)

    quantities: dict[str, tuple[Decimal, int]] = {}
    for row in rows:
        if row.estimated_quantity is not None and row.quantity_unit_code is not None:
            total, n = quantities.get(row.quantity_unit_code, (Decimal(0), 0))
            quantities[row.quantity_unit_code] = (total + row.estimated_quantity, n + 1)
    months = through or 0
    monthly, complete = _monthly_count(session, year, months, ("lopc", "lopc"))
    with_details = sum(1 for row in rows if row.detail_id is not None)
    warnings = []
    if monthly is not None and monthly != len(rows):
        warnings.append(
            f"The monthly LOPC count is {monthly}; {len(rows)} Spill / Release "
            f"{'record is' if len(rows) == 1 else 'records are'} documented. These record-derived "
            "views cover the documented records only."
        )
    if with_details < len(rows):
        missing = len(rows) - with_details
        warnings.append(
            f"{missing} of {len(rows)} Spill / Release records have no LOPC details; "
            "their values show as Unknown."
        )
    process_safety = [
        None
        if row.process_safety_incident is None
        else ("yes" if row.process_safety_incident else "no")
        for row in rows
    ]
    return LopcRecordsResponse(
        year=year,
        through_month=through,
        records=len(rows),
        with_details=with_details,
        monthly_count=monthly,
        monthly_count_complete=complete,
        by_failure_mechanism=_counts(
            [row.failure_mechanism_code for row in rows], named("lopc_failure_mechanism")
        ),
        by_material=text_counts([row.material_name for row in rows]),
        by_equipment=text_counts([row.equipment_tag for row in rows]),
        by_containment=_counts(
            [row.secondary_containment_status_code for row in rows],
            named("secondary_containment_status"),
        ),
        by_process_safety=_counts(process_safety, lambda k: "Yes" if k == "yes" else "No"),
        quantities=[
            QuantityOut(
                unit_code=unit, unit_name=named("quantity_unit")(unit), total=total, records=n
            )
            for unit, (total, n) in sorted(quantities.items())
        ],
        records_without_quantity=sum(1 for row in rows if row.estimated_quantity is None),
        recent=_summaries(session, [row.id for row in rows[:RECENT]]),
        warnings=warnings,
    )


def serious_risk(
    session: Session, *, year: int, through: int | None, near_misses: bool
) -> SeriousRiskResponse:
    r, s, lopc = IncidentRecord, IncidentSeriousRiskDetails, IncidentLopcDetails
    category = categories.BY_CODE["psif"]
    types = _event_types(category, near_misses)
    rows = session.execute(
        select(
            r.id,
            r.incident_date,
            r.area_id,
            Area.name.label("area_name"),
            s.potential_severity_code,
            lopc.contributing_factor_code,
        )
        .join(s, s.incident_record_id == r.id)
        .outerjoin(Area, Area.id == r.area_id)
        .outerjoin(lopc, lopc.incident_record_id == r.id)
        .where(
            r.status == "active",
            r.event_type.in_(types),
            s.is_psif.is_(True),
            _window(year, through),
        )
        .order_by(r.incident_date.desc(), r.id.desc())
    ).all()
    ids = [row.id for row in rows]
    names = _names(session)
    summaries = {summary.id: summary for summary in _summaries(session, ids)}
    classification_ids: dict[int, list[tuple[int, str]]] = {}
    if ids:
        c, rc = MetricCategory, IncidentRecordClassification
        for record_id, category_id, name in session.execute(
            select(r.id, c.id, c.name)
            .join(c, c.id == r.classification_category_id)
            .where(r.id.in_(ids))
            .union_all(
                select(rc.incident_record_id, c.id, c.name)
                .join(c, c.id == rc.classification_category_id)
                .where(rc.incident_record_id.in_(ids))
            )
        ).all():
            classification_ids.setdefault(record_id, []).append((category_id, name))
    by_classification: Counter[tuple[str | None, str]] = Counter()
    for record_id in ids:
        found = classification_ids.get(record_id)
        if not found:
            by_classification[(None, "Unclassified")] += 1
        for category_id, name in found or ():
            by_classification[(str(category_id), name)] += 1
    area_names = {str(row.area_id): row.area_name for row in rows if row.area_id is not None}
    months = through or 0
    monthly, complete = _monthly_count(session, year, months, ("psif", "psif"))
    per_month = Counter(row.incident_date.month for row in rows)
    stored: dict[int, int] = {}
    if months:
        v, c, sec = MonthlyMetricValue, MetricCategory, MetricSection
        stored = dict(
            session.execute(
                select(v.reporting_month, v.value)
                .join(c, c.id == v.category_id)
                .join(sec, sec.id == c.section_id)
                .where(
                    sec.metric_set == categories.INCIDENTS_METRIC_SET,
                    sec.code == "psif",
                    c.code == "psif",
                    v.reporting_year == year,
                    v.reporting_month <= months,
                )
            ).all()
        )
    warnings = []
    if monthly is not None and monthly > len(rows):
        warnings.append(
            f"The monthly PSIF count is {monthly}; {len(rows)} "
            f"{'record is' if len(rows) == 1 else 'records are'} designated PSIF. The record views "
            "are incomplete until every PSIF event is documented."
        )
    if not near_misses:
        warnings.append("Near misses are not included: they are not available to you.")
    return SeriousRiskResponse(
        year=year,
        through_month=through,
        includes_near_misses=near_misses,
        psif_records=len(rows),
        monthly_count=monthly,
        monthly_count_complete=complete,
        monthly=[
            MonthCountOut(month=m, records=per_month.get(m, 0), monthly_count=stored.get(m))
            for m in range(1, months + 1)
        ],
        by_classification=[
            CountOut(key=key, name=name, count=n)
            for (key, name), n in sorted(
                by_classification.items(), key=lambda i: (i[0][0] is None, -i[1], i[0][1])
            )
        ],
        by_area=_counts(
            [None if row.area_id is None else str(row.area_id) for row in rows],
            lambda key: area_names.get(key, key),
            unknown_key=None,
        ),
        by_contributing_factor=_counts(
            [row.contributing_factor_code for row in rows],
            lambda key: names.get(LOPC_CONTRIBUTING_FACTOR.removeprefix("metric:"), {}).get(
                key, key
            ),
            unknown_key=None,
        ),
        by_severity=_counts(
            [row.potential_severity_code for row in rows],
            lambda key: names.get("potential_severity", {}).get(key, key),
            unknown_key=None,
        ),
        recent=[summaries[record_id] for record_id in ids[:RECENT]],
        warnings=warnings,
    )
