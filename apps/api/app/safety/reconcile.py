"""Read-only reconciliation of the Safety datastore.

    python -m app.safety.reconcile --year 2026
    python -m app.safety.reconcile --year 2026 \\
        --incidents import_templates/safety_incidents_2026_lcy_ehs.mapping.json \\
        --hours import_templates/safety_performance_hours_lcy_ehs.mapping.json \\
        --trir import_templates/safety_trir_experience_history_lcy_ehs.mapping.json \\
        --records import_templates/safety_incident_records_2026_lcy_ehs.review.json \\
        --behavior import_templates/safety_behavior_2026_lcy_ehs.mapping.json \\
        --pha import_templates/psm_pha_2026_300_400_600.mapping.json [--json]

Everything runs in one READ ONLY transaction that is rolled back: the command
cannot write. It checks that the schema is at the shipped migration head, that
every Safety relation is a permanent table, that the TRIR inputs are complete,
that monthly totals, classifications and records agree, and, for each reviewed
file given, that everything the file reports is stored with the same value.

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
from sqlalchemy import extract, func, select, text
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
from app.safety.records import legacy_import as records_import
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


def check_import_runs(session: Session, now: dt.datetime) -> list[Finding]:
    failed = session.scalar(
        select(func.count()).select_from(ImportRun).where(ImportRun.status == "failed")
    )
    stale = session.scalar(
        select(func.count())
        .select_from(ImportRun)
        .where(ImportRun.status == "running", ImportRun.started_at < now - STALE_RUN)
    )
    findings = []
    if failed:
        findings.append(
            _warn("import_runs", f"{failed} import runs failed; see safety.import_runs.")
        )
    if stale:
        findings.append(
            _warn("import_runs", f"{stale} import runs never finished; see safety.import_runs.")
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
    for path in sources.incidents:
        findings += check_incidents_file(session, path)
    if sources.hours:
        findings += check_hours_file(session, sources.hours, site_today(at))
    if sources.trir:
        findings += check_trir_file(session, sources.trir)
    if sources.records:
        findings += check_records_file(session, sources.records)
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
    parser.add_argument("--behavior", type=Path)
    parser.add_argument("--pha", type=Path)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    sources = Sources(
        incidents=args.incidents,
        hours=args.hours,
        trir=args.trir,
        records=args.records,
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
