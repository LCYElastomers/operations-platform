"""Read-only reconciliation of the Safety datastore.

    python -m app.safety.reconcile --year 2026
    python -m app.safety.reconcile --year 2026 \\
        --incidents import_templates/safety_incidents_2026_lcy_ehs.mapping.json \\
        --hours import_templates/safety_performance_hours_lcy_ehs.mapping.json \\
        --trir import_templates/safety_trir_experience_history_lcy_ehs.mapping.json \\
        --records import_templates/safety_incident_records_2026_lcy_ehs.review.json \\
        --details import_templates/safety_incident_details_2026_lcy_ehs.mapping.json \\
        --behavior import_templates/safety_behavior_2026_lcy_ehs.mapping.json \\
        --pha import_templates/psm_pha_2026_300_400_600.mapping.json [--json]

Everything runs in one READ ONLY transaction that is rolled back: the command
cannot write. It checks that the schema is at the shipped migration head, that
every Safety relation is a permanent table, that the TRIR inputs are complete,
that monthly totals, classifications and records agree, that record details
follow their rules and the PSIF, LOPC, PIT and damage counts agree with the
records, reports each Event Experience category, and, for each reviewed file
given, that everything the file reports is stored with the same value.

Exit status: 0 nothing to resolve, 1 discrepancies found, 2 unreadable input or
database unavailable. A discrepancy is reported, never resolved here: the
stored value and the file value are both shown and neither is chosen.
"""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import ColumnElement, and_, exists, extract, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.schema_state import schema_state
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety import legacy_import as metrics_import
from app.safety.behavior import legacy_import as behavior_import
from app.safety.behavior.repository import DatabaseBehaviorRepository
from app.safety.imports.models import ImportRun
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.performance import legacy_import as hours_import
from app.safety.performance.repository import DatabasePerformanceRepository
from app.safety.performance.service import trir_inputs
from app.safety.psm import pha_import
from app.safety.psm.store import PsmStore
from app.safety.records import categories, detail_import, details, insights
from app.safety.records import legacy_import as records_import
from app.safety.records.detail_models import IncidentRecordClassification
from app.safety.records.models import IncidentRecord
from app.safety.records.repository import (
    CLASSIFICATION_SECTION,
    INCIDENTS_METRIC_SET,
    RecordRepository,
)
from app.safety.records.service import reconciliation_state
from app.safety.repository import DatabaseSafetyMetricsRepository
from app.safety.site_calendar import site_today
from app.safety.trir import legacy_import as trir_import
from app.safety.trir import service as trir_service
from app.safety.trir.repository import TrirRepository

Status = Literal["ok", "warning", "discrepancy"]
# Schemas holding Safety data and its audit trail.
SCHEMAS = ("safety", "core")
STALE_RUN = dt.timedelta(hours=1)


@dataclass(frozen=True)
class Finding:
    check: str
    status: Status
    message: str


@dataclass(frozen=True)
class Sources:
    incidents: Sequence[Path] = ()
    hours: Path | None = None
    trir: Path | None = None
    records: Path | None = None
    details: Path | None = None
    behavior: Path | None = None
    pha: Path | None = None


def _ok(check: str, message: str) -> Finding:
    return Finding(check, "ok", message)


def _warn(check: str, message: str) -> Finding:
    return Finding(check, "warning", message)


def _bad(check: str, message: str) -> Finding:
    return Finding(check, "discrepancy", message)


def _sample(items: Sequence[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


# Database-wide checks ------------------------------------------------------------------


def check_schema(session: Session) -> list[Finding]:
    state = schema_state(session.connection())
    if state.at_head:
        return [_ok("schema", f"Schema is at the migration head ({state.head}).")]
    current = ", ".join(state.current) or "none"
    return [_bad("schema", f"Schema is at {current}; this code expects {state.head}.")]


def check_relations(session: Session) -> list[Finding]:
    """Every Safety relation must be a permanent, logged table (or its sequence or
    index): no unlogged, temporary or materialized storage holds accepted data."""
    rows = session.execute(
        text(
            "SELECT n.nspname, c.relname, c.relkind, c.relpersistence "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(:schemas) AND c.relkind IN ('r', 'p', 'm', 'v', 'f')"
        ),
        {"schemas": list(SCHEMAS)},
    ).all()
    tables = [r for r in rows if r.relkind in ("r", "p")]
    problems = [
        f"{r.nspname}.{r.relname} ({'unlogged' if r.relpersistence == 'u' else 'temporary'})"
        for r in rows
        if r.relpersistence != "p"
    ]
    problems += [
        f"{r.nspname}.{r.relname} ({'materialized view' if r.relkind == 'm' else 'foreign table'})"
        for r in rows
        if r.relkind in ("m", "f")
    ]
    if problems:
        return [_bad("storage", f"Non-permanent Safety relations: {_sample(problems)}.")]
    return [
        _ok(
            "storage",
            f"All {len(tables)} tables in {', '.join(SCHEMAS)} are permanent and logged.",
        )
    ]


def _runs_by_importer(session: Session, *conditions: ColumnElement[bool]) -> str:
    rows = session.execute(
        select(ImportRun.importer, func.count())
        .where(*conditions)
        .group_by(ImportRun.importer)
        .order_by(ImportRun.importer)
    ).all()
    return ", ".join(f"{importer} {n}" for importer, n in rows)


def check_import_runs(session: Session, now: dt.datetime) -> list[Finding]:
    """Failed runs, and runs that never finished (possibly partial)."""
    failed = _runs_by_importer(session, ImportRun.status == "failed")
    stale = _runs_by_importer(
        session, ImportRun.status == "running", ImportRun.started_at < now - STALE_RUN
    )
    findings = []
    if failed:
        findings.append(
            _warn("import_runs", f"Import runs failed ({failed}); see safety.import_runs.")
        )
    if stale:
        findings.append(
            _warn("import_runs", f"Import runs never finished ({stale}); see safety.import_runs.")
        )
    return findings or [_ok("import_runs", "No failed or unfinished import runs.")]


# Year checks ---------------------------------------------------------------------------


def check_trir(session: Session, year: int) -> list[Finding]:
    performance = DatabasePerformanceRepository(session)
    result = trir_service.experience(
        TrirRepository(session).facts(),
        lambda years: trir_inputs(performance, years),
        RecordRepository(session).monthly_totals,
        year=year,
        through_month=None,
    )
    current = result.current
    inputs = (
        f"recordables {current.recordables if current.recordables is not None else 'unknown'}, "
        f"hours {current.hours if current.hours is not None else 'unknown'}, "
        f"through month {current.through_month or 'none'}"
    )
    findings = []
    if current.display is not None:
        findings.append(_ok("trir", f"{year} TRIR {current.display} ({inputs})."))
    else:
        missing = [f"{m.year}-{m.month:02d} {m.reason}" for m in current.missing_months]
        findings.append(
            _warn(
                "trir",
                f"{year} TRIR unavailable: {current.unavailable_reason or 'no complete months'} "
                f"({inputs}; missing {_sample(missing) or 'none'}).",
            )
        )
    findings += [
        _warn("trir_data_quality", item.message)
        for item in result.data_quality
        if item.status == "warning"
    ]
    return findings


def check_totals_against_records(session: Session, year: int) -> list[Finding]:
    """Monthly Incident and Near Miss totals against active records. Records are
    documentation of the totals; fewer records than the total is incomplete
    documentation, but records the totals do not count are a discrepancy."""
    repository = RecordRepository(session)
    totals = repository.monthly_totals(year)
    documented = repository.documented_counts(year)
    missing: list[str] = []
    wrong: list[str] = []
    for event_type in ("incident", "near_miss"):
        for month in range(1, 13):
            total = totals.get((event_type, month))
            count = documented.get((event_type, month), 0)
            state = reconciliation_state(total, count)
            where = f"{year}-{month:02d} {event_type}"
            shown = "unreported" if total is None else total
            if state == "records_missing":
                missing.append(f"{where} total {shown}, records {count}")
            elif state in (
                "records_exceed_total",
                "explicit_zero_with_records",
                "total_unreported_with_records",
            ):
                wrong.append(f"{where} total {shown}, records {count} ({state})")
    findings = [_bad("totals_vs_records", f"Records not counted: {w}.") for w in wrong]
    if missing:
        findings.append(
            _warn(
                "totals_vs_records",
                f"{len(missing)} months have fewer records than their total "
                f"(documentation incomplete): {_sample(missing)}.",
            )
        )
    return findings or [_ok("totals_vs_records", f"{year} totals and records agree.")]


def check_classifications(session: Session, year: int) -> list[Finding]:
    """Stored monthly classification counts (what TRIR uses) against active
    records with that classification, matched by category code."""
    c, s, v, r = MetricCategory, MetricSection, MonthlyMetricValue, IncidentRecord
    in_year = (r.incident_date >= dt.date(year, 1, 1), r.incident_date < dt.date(year + 1, 1, 1))
    month = extract("month", r.incident_date)
    classified = {
        (code, int(m)): n
        for code, m, n in session.execute(
            select(c.code, month, func.count())
            .join(c, c.id == r.classification_category_id)
            .where(r.status == "active", *in_year)
            .group_by(c.code, month)
        ).all()
    }
    stored = {
        (code, m): value
        for code, m, value in session.execute(
            select(c.code, v.reporting_month, v.value)
            .join(c, c.id == v.category_id)
            .join(s, s.id == c.section_id)
            .where(
                s.metric_set == INCIDENTS_METRIC_SET,
                s.code == CLASSIFICATION_SECTION,
                v.reporting_year == year,
            )
        ).all()
    }
    findings = []
    fewer = []
    for (code, m), count in sorted(classified.items()):
        value = stored.get((code, m))
        if value is None:
            findings.append(
                _bad(
                    "classifications",
                    f"{year}-{m:02d} {code}: {count} records, monthly count unreported.",
                )
            )
        elif count > value:
            findings.append(
                _bad(
                    "classifications",
                    f"{year}-{m:02d} {code}: {count} records, monthly count {value}.",
                )
            )
    for (code, m), value in sorted(stored.items()):
        count = classified.get((code, m), 0)
        if value is not None and count < value:
            fewer.append(f"{year}-{m:02d} {code} count {value}, records {count}")
    if fewer:
        findings.append(
            _warn(
                "classifications",
                f"{len(fewer)} classification counts have fewer records "
                f"(documentation incomplete): {_sample(fewer)}.",
            )
        )
    unclassified = [
        number or f"record {record_id}"
        for record_id, number in session.execute(
            select(r.id, r.incident_number)
            .where(
                r.status == "active",
                r.event_type == "incident",
                r.classification_category_id.is_(None),
                *in_year,
            )
            .order_by(r.incident_date, r.id)
        ).all()
    ]
    if unclassified:
        findings.append(
            _warn(
                "classifications",
                f"{len(unclassified)} active {year} incident records have no classification "
                f"(an owner must classify them): {_sample(unclassified)}.",
            )
        )
    excluded = dict(
        session.execute(
            select(r.status, func.count()).where(r.status != "active", *in_year).group_by(r.status)
        ).all()
    )
    if excluded:
        shown = ", ".join(f"{n} {state}" for state, n in sorted(excluded.items()))
        findings.append(_ok("classifications", f"Excluded from counts as not active: {shown}."))
    return findings or [_ok("classifications", f"{year} classifications agree with records.")]


# Record details and Event Experience -----------------------------------------------------

DETAIL_TABLES = (
    "incident_detail_codes",
    "incident_record_classifications",
    "incident_lopc_details",
    "incident_damage_details",
    "incident_pit_details",
    "incident_serious_risk_details",
)
# Stored monthly count (section, category) -> the records it counts.
AGGREGATES: tuple[tuple[str, tuple[str, str], Callable[[], ColumnElement[bool]]], ...] = (
    ("psif", ("psif", "psif"), categories.is_psif),
    (
        "lopc",
        ("lopc", "lopc"),
        lambda: and_(
            IncidentRecord.event_type == "incident", categories.has_classification("spill_release")
        ),
    ),
    (
        "pit",
        ("pit", "pit"),
        lambda: and_(
            IncidentRecord.event_type == "incident", categories.has_classification("pit_accident")
        ),
    ),
    (
        "property_equipment_damage",
        ("property_equipment_damage", "property_equipment_damage"),
        lambda: and_(
            IncidentRecord.event_type == "incident",
            or_(
                categories.has_classification("property_damage"),
                categories.has_classification("equipment_damage_failure"),
            ),
        ),
    ),
)
# Classification -> the detail a record with it should carry.
RECOMMENDED_DETAIL = {
    "spill_release": details.LOPC,
    "property_damage": details.DAMAGE,
    "equipment_damage_failure": details.DAMAGE,
    "pit_accident": details.PIT,
}


def check_detail_storage(session: Session) -> list[Finding]:
    """The record-detail tables exist and are permanent, logged tables."""
    rows = dict(
        session.execute(
            text(
                "SELECT c.relname, c.relpersistence FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'safety' AND c.relkind = 'r' AND c.relname = ANY(:names)"
            ),
            {"names": list(DETAIL_TABLES)},
        ).all()
    )
    problems = [
        f"safety.{name} ({'missing' if name not in rows else 'not permanent'})"
        for name in DETAIL_TABLES
        if rows.get(name) != "p"
    ]
    if problems:
        return [_bad("detail_storage", f"Record-detail tables: {_sample(problems)}.")]
    return [
        _ok(
            "detail_storage",
            f"All {len(DETAIL_TABLES)} record-detail tables are permanent and logged.",
        )
    ]


def check_event_experience(session: Session, year: int, today: dt.date) -> list[Finding]:
    """Each Event Experience category: completeness, the latest event, and the year's
    classified records against the stored monthly count."""
    if year > today.year:
        return [_warn("event_experience", f"{year} has not started.")]
    as_of = today if year == today.year else dt.date(year, 12, 31)
    result = insights.event_experience(session, year=year, as_of=as_of, near_misses=True)
    findings = []
    for category in result.categories:
        latest = category.latest_event_date
        when = (
            f"latest event {latest.isoformat()} ({category.days_since_latest_event} days "
            f"before {as_of.isoformat()})"
            if latest
            else "no event found"
        )
        monthly = "unreported" if category.monthly_count is None else category.monthly_count
        message = (
            f"{category.name}: {category.status}; {when}; {category.ytd_events} {year} "
            f"records, monthly count {monthly}."
        )
        if category.warnings:
            message += " " + " ".join(category.warnings)
        complete = category.status in ("complete", "no_event_in_scope")
        findings.append(
            _ok("event_experience", message) if complete else _warn("event_experience", message)
        )
    return findings


def _record_codes(session: Session) -> dict[int, set[str]]:
    """Active records' classification codes (primary and further)."""
    r, c, rc = IncidentRecord, MetricCategory, IncidentRecordClassification
    codes: dict[int, set[str]] = {}
    for record_id, code in session.execute(
        select(r.id, c.code)
        .join(c, c.id == r.classification_category_id)
        .where(r.status == "active")
        .union_all(
            select(r.id, c.code)
            .join(rc, rc.incident_record_id == r.id)
            .join(c, c.id == rc.classification_category_id)
            .where(r.status == "active")
        )
    ).all():
        codes.setdefault(record_id, set()).add(code)
    return codes


def _label(number: str | None, record_id: int) -> str:
    return number or f"record {record_id}"


def check_record_details(session: Session, year: int) -> list[Finding]:
    """Detail rows against their rules: qualifying classification, known codes,
    paired values, one row per record; and qualifying records without detail."""
    r = IncidentRecord
    codes = _record_codes(session)
    known = {
        taxonomy: {code for code, _, _ in entries}
        for taxonomy, entries in RecordRepository(session).detail_codes().items()
    }
    findings: list[Finding] = []
    for spec in details.SPECS:
        model = spec.model
        rows = session.execute(
            select(model, r.incident_number, r.status).join(r, r.id == model.incident_record_id)
        ).all()
        unqualified, invalid, unpaired = [], [], []
        for detail, number, status in rows:
            values = details.stored_values(spec, detail)
            label = _label(number, detail.incident_record_id)
            for column, taxonomy in spec.coded.items():
                if values[column] is not None and values[column] not in known.get(taxonomy, ()):
                    invalid.append(f"{label} {column}={values[column]}")
            if spec is details.LOPC and (values["estimated_quantity"] is None) != (
                values["quantity_unit_code"] is None
            ):
                unpaired.append(f"{label} quantity without unit")
            if spec is details.DAMAGE and (values["estimated_cost"] is None) != (
                values["currency_code"] is None
            ):
                unpaired.append(f"{label} cost without currency")
            kind = values.get("damage_kind_code")
            if status != "active" or (
                kind is not None and kind not in details.DAMAGE_KIND_CLASSIFICATION
            ):
                continue
            problem = details.requirement_problem(
                spec, values, codes.get(detail.incident_record_id, set())
            )
            if problem:
                unqualified.append(label)
        label = spec.label.lower()
        if unqualified:
            findings.append(
                _bad(
                    "detail_classification",
                    f"{len(unqualified)} active records have {label} without a qualifying "
                    f"classification ({spec.requirement}): {_sample(unqualified)}.",
                )
            )
        if invalid:
            findings.append(_bad("detail_codes", f"Unknown codes in {label}: {_sample(invalid)}."))
        if unpaired:
            findings.append(_bad("detail_pairs", f"In {label}: {_sample(unpaired)}."))
        duplicates = session.scalar(
            select(func.count()).select_from(
                select(model.incident_record_id)
                .group_by(model.incident_record_id)
                .having(func.count() > 1)
                .subquery()
            )
        )
        if duplicates:
            findings.append(
                _bad("detail_duplicates", f"{duplicates} records have more than one {label} row.")
            )
    rc = IncidentRecordClassification
    duplicate_links = session.scalar(
        select(func.count()).select_from(
            select(rc.incident_record_id, rc.classification_category_id)
            .group_by(rc.incident_record_id, rc.classification_category_id)
            .having(func.count() > 1)
            .subquery()
        )
    )
    if duplicate_links:
        findings.append(
            _bad(
                "detail_duplicates",
                f"{duplicate_links} further classifications are stored more than once.",
            )
        )

    in_year = (r.incident_date >= dt.date(year, 1, 1), r.incident_date < dt.date(year + 1, 1, 1))
    for classification, spec in RECOMMENDED_DETAIL.items():
        missing = [
            _label(number, record_id)
            for record_id, number in session.execute(
                select(r.id, r.incident_number)
                .where(
                    r.status == "active",
                    r.event_type == "incident",
                    categories.has_classification(classification),
                    ~exists().where(spec.model.incident_record_id == r.id),
                    *in_year,
                )
                .order_by(r.incident_date, r.id)
            ).all()
        ]
        if missing:
            findings.append(
                _warn(
                    "detail_missing",
                    f"{len(missing)} active {year} {classification} records have no "
                    f"{spec.label.lower()}: {_sample(missing)}.",
                )
            )
    return findings or [_ok("record_details", "Record details follow their rules.")]


def check_aggregates_against_records(session: Session, year: int) -> list[Finding]:
    """PSIF, LOPC, PIT and Property / Equipment Damage monthly counts against the
    active records they count. Fewer records is incomplete documentation; more
    records than the count is a discrepancy."""
    r, c, s, v = IncidentRecord, MetricCategory, MetricSection, MonthlyMetricValue
    month = extract("month", r.incident_date)
    in_year = (r.incident_date >= dt.date(year, 1, 1), r.incident_date < dt.date(year + 1, 1, 1))
    findings: list[Finding] = []
    for name, (section, category), condition in AGGREGATES:
        records = {
            int(m): n
            for m, n in session.execute(
                select(month, func.count())
                .where(r.status == "active", condition(), *in_year)
                .group_by(month)
            ).all()
        }
        stored = dict(
            session.execute(
                select(v.reporting_month, v.value)
                .join(c, c.id == v.category_id)
                .join(s, s.id == c.section_id)
                .where(
                    s.metric_set == INCIDENTS_METRIC_SET,
                    s.code == section,
                    c.code == category,
                    v.reporting_year == year,
                )
            ).all()
        )
        check = f"{name}_vs_records"
        over, fewer = [], []
        for m in range(1, 13):
            count, value = records.get(m, 0), stored.get(m)
            if count and (value is None or count > value):
                shown = "unreported" if value is None else value
                over.append(f"{year}-{m:02d} count {shown}, records {count}")
            elif value is not None and count < value:
                fewer.append(f"{year}-{m:02d} count {value}, records {count}")
        findings += [_bad(check, f"Records not counted: {item}.") for item in over]
        if fewer:
            findings.append(
                _warn(
                    check,
                    f"{len(fewer)} months have fewer records than the count "
                    f"(documentation incomplete): {_sample(fewer)}.",
                )
            )
        if not over and not fewer:
            total = sum(records.values())
            findings.append(_ok(check, f"{year} counts and {total} records agree."))
    return findings


# Reviewed source files -----------------------------------------------------------------


def check_incidents_file(session: Session, path: Path) -> list[Finding]:
    check = f"file:{path.name}"
    mapping = metrics_import.load_mapping(path)
    plan = metrics_import.plan_import(DatabaseSafetyMetricsRepository(session), mapping)
    findings = [
        _bad(
            check,
            f"The file itself: {d.section}/{d.category} states {d.expected}, months "
            f"sum to {d.calculated if d.calculated is not None else 'nothing'}.",
        )
        for d in metrics_import.total_discrepancies(mapping)
    ]
    findings += [_bad(check, f"Unknown category {s}/{c}.") for s, c in plan.unknown]
    findings += [
        _bad(
            check,
            f"{mapping.year}-{m:02d} {s}/{c}: stored {old}, file "
            f"{'unreported' if new is None else new}.",
        )
        for s, c, m, old, new in plan.differing
    ]
    if plan.changes:
        findings.append(
            _bad(check, f"{len(plan.changes)} values reported in the file are not stored.")
        )
    return findings or [_ok(check, f"All {plan.unchanged} reported values are stored.")]


def check_hours_file(session: Session, path: Path, today: dt.date) -> list[Finding]:
    check = f"file:{path.name}"
    mapping = hours_import.load_mapping(path)
    plan = hours_import.plan_import(DatabasePerformanceRepository(session), mapping, today=today)
    findings = [_bad(check, reason) for reason in plan.blocking]
    if plan.hours or plan.annual:
        months = [f"{h.year}-{h.month:02d}" for h in plan.hours]
        findings.append(
            _bad(
                check,
                f"Not stored: {len(plan.hours)} months ({_sample(months)}), "
                f"{len(plan.annual)} annual rows.",
            )
        )
    return findings or [_ok(check, f"All {plan.unchanged} rows are stored.")]


def check_trir_file(session: Session, path: Path) -> list[Finding]:
    check = f"file:{path.name}"
    mapping = trir_import.load_mapping(path)
    plan = trir_import.plan_import(TrirRepository(session).facts(), mapping)
    findings = [
        _bad(check, f"{year} {field}: stored {stored}, file {new}.")
        for year, field, stored, new in plan.differing
    ]
    if plan.inserts:
        findings.append(_bad(check, f"Years not stored: {[e.year for e in plan.inserts]}."))
    return findings or [_ok(check, f"All {len(plan.unchanged)} years are stored.")]


def check_records_file(session: Session, path: Path) -> list[Finding]:
    check = f"file:{path.name}"
    review = records_import.load_review(path)
    to_create, done, problems = records_import.plan(RecordRepository(session), review)
    findings = [_bad(check, problem) for problem in problems]
    if to_create:
        findings.append(
            _bad(
                check,
                f"{len(to_create)} included records are not stored: "
                f"{_sample([c.candidate_id for c in to_create])}.",
            )
        )
    return findings or [_ok(check, f"All {len(done)} included records are stored.")]


def check_details_file(session: Session, path: Path) -> list[Finding]:
    check = f"file:{path.name}"
    mapping = detail_import.load_mapping(path)
    repository = RecordRepository(session)
    plan = detail_import.Plan()
    pending = [
        entry.reference
        for entry in mapping.records
        if detail_import.compare(repository, entry, plan) is not None
    ]
    findings = [_bad(check, problem) for problem in plan.problems]
    if pending:
        findings.append(
            _bad(check, f"{len(pending)} mapped records lack their details: {_sample(pending)}.")
        )
    return findings or [
        _ok(check, f"All {len(mapping.records)} mapped records' details are stored.")
    ]


def check_behavior_file(session: Session, path: Path) -> list[Finding]:
    check = f"file:{path.name}"
    mapping = behavior_import.load_mapping(path)
    plan = behavior_import.plan_import(DatabaseBehaviorRepository(session), mapping)
    findings = [_bad(check, f"Unknown category {c}.") for c in plan.unknown]
    findings += [
        _bad(check, f"{c}: stored {old}, file {'blank' if new is None else new}.")
        for c, old, new in plan.differing
    ]
    if plan.changes:
        findings.append(_bad(check, f"{len(plan.changes)} counts in the file are not stored."))
    return findings or [_ok(check, f"All {plan.unchanged} counts are stored.")]


def check_pha_file(session: Session, path: Path) -> list[Finding]:
    check = f"file:{path.name}"
    mapping = pha_import.PhaMapping.model_validate_json(path.read_text(encoding="utf-8"))
    plan = pha_import.plan(PsmStore(session), mapping)
    summary = plan.summary()
    findings = [_bad(check, conflict) for conflict in plan.conflicts]
    findings += [_warn(check, difference) for difference in plan.differences]
    if summary["newRecommendations"] or summary["newScenarios"]:
        findings.append(
            _bad(
                check,
                f"Not stored: {summary['newRecommendations']} recommendations, "
                f"{summary['newScenarios']} scenarios.",
            )
        )
    scenarios = [s for r in mapping.recommendations for s in r.scenarios]
    risks = ", ".join(
        f"{risk} {sum(s.risk == risk for s in scenarios)}" for risk in ("high", "medium", "low")
    )
    if not any(f.status == "discrepancy" for f in findings):
        findings.append(
            _ok(
                check,
                f"{len(mapping.recommendations)} recommendations and {len(scenarios)} "
                f"scenarios ({risks}) are stored.",
            )
        )
    return findings


# Command -------------------------------------------------------------------------------


def reconcile(
    session: Session,
    year: int,
    sources: Sources,
    *,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> list[Finding]:
    """All checks. Reads only; ``main`` runs them in a READ ONLY transaction."""
    at = now()
    findings = [*check_schema(session), *check_relations(session)]
    if findings[0].status != "ok":
        return findings
    findings += check_import_runs(session, at)
    findings += check_trir(session, year)
    findings += check_totals_against_records(session, year)
    findings += check_classifications(session, year)
    findings += check_detail_storage(session)
    findings += check_event_experience(session, year, site_today(at))
    findings += check_record_details(session, year)
    findings += check_aggregates_against_records(session, year)
    for path in sources.incidents:
        findings += check_incidents_file(session, path)
    if sources.hours:
        findings += check_hours_file(session, sources.hours, site_today(at))
    if sources.trir:
        findings += check_trir_file(session, sources.trir)
    if sources.records:
        findings += check_records_file(session, sources.records)
    if sources.details:
        findings += check_details_file(session, sources.details)
    if sources.behavior:
        findings += check_behavior_file(session, sources.behavior)
    if sources.pha:
        findings += check_pha_file(session, sources.pha)
    return findings


def _print(findings: Sequence[Finding]) -> None:
    labels = {"ok": "OK         ", "warning": "WARNING    ", "discrepancy": "DISCREPANCY"}
    for finding in findings:
        print(f"{labels[finding.status]} [{finding.check}] {finding.message}")
    counts = {s: sum(f.status == s for f in findings) for s in labels}
    print(
        f"\n{counts['discrepancy']} discrepancies, {counts['warning']} warnings, "
        f"{counts['ok']} checks passed. Nothing was written."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.reconcile")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--incidents", type=Path, action="append", default=[])
    parser.add_argument("--hours", type=Path)
    parser.add_argument("--trir", type=Path)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--details", type=Path)
    parser.add_argument("--behavior", type=Path)
    parser.add_argument("--pha", type=Path)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    sources = Sources(
        incidents=args.incidents,
        hours=args.hours,
        trir=args.trir,
        records=args.records,
        details=args.details,
        behavior=args.behavior,
        pha=args.pha,
    )
    try:
        with get_sessionmaker()() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            try:
                findings = reconcile(session, args.year, sources)
            finally:
                session.rollback()
    except (OSError, ValueError, ValidationError) as error:
        print(f"Unreadable source file: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    except DatabaseNotConfiguredError:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        return 2
    except SQLAlchemyError as error:
        print(f"Database unavailable: {type(error).__name__}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {
                    "year": args.year,
                    "discrepancies": sum(f.status == "discrepancy" for f in findings),
                    "warnings": sum(f.status == "warning" for f in findings),
                    "findings": [asdict(f) for f in findings],
                },
                indent=2,
            )
        )
    else:
        _print(findings)
    return 1 if any(f.status == "discrepancy" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
