"""Read-only comparison of stored monthly values vs record-derived counts.

Before a reporting period is switched from manually typed totals to
record-derived totals, run:

    python -m app.safety.records.compare_derived --year 2026
    python -m app.safety.records.compare_derived --year 2026 --month 10
    python -m app.safety.records.compare_derived --year 2026 --json

Nothing is written. Each differing cell reports the stored (manual) value,
the value that a rebuild would write from active records, the difference,
and the supporting active record numbers. Exit 0 when every derived cell
already matches; 1 when differences exist; 2 on configuration or IO errors.

Does not create synthetic records to force historical totals to match.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety.models import MonthlyMetricValue
from app.safety.records import aggregation
from app.safety.records.models import IncidentRecord


@dataclass(frozen=True)
class CellDifference:
    section: str
    category: str
    year: int
    month: int
    stored: int | None
    derived: int
    difference: int
    records: list[str]


def month_differences(session: Session, year: int, month: int) -> list[CellDifference]:
    """Stored vs record-derived values for one month of the derived sections."""
    categories = aggregation._load_categories(session)
    derived_counts = aggregation.month_counts(session, categories, year, month)
    v = MonthlyMetricValue
    stored_rows = {
        category_id: value
        for category_id, value in session.execute(
            select(v.category_id, v.value).where(
                v.reporting_year == year,
                v.reporting_month == month,
                v.category_id.in_([c.id for c in categories.all]),
            )
        )
    }
    start, end = aggregation.month_bounds(year, month)
    supporting = [
        (number, event_type)
        for number, event_type in session.execute(
            select(IncidentRecord.incident_number, IncidentRecord.event_type)
            .where(
                IncidentRecord.status == "active",
                IncidentRecord.incident_date >= start,
                IncidentRecord.incident_date < end,
            )
            .order_by(IncidentRecord.incident_number)
        )
    ]
    record_labels = [f"{number} ({event_type})" for number, event_type in supporting]

    out: list[CellDifference] = []
    for category in categories.all:
        stored = stored_rows.get(category.id)
        derived = derived_counts.get(category.id, 0)
        # Unreported and a derived 0 with no active records both mean "no events".
        if stored is None and derived == 0 and not supporting:
            continue
        stored_value = 0 if stored is None else stored
        if stored_value == derived:
            continue
        out.append(
            CellDifference(
                section=category.section,
                category=category.code,
                year=year,
                month=month,
                stored=stored,
                derived=derived,
                difference=derived - stored_value,
                records=record_labels,
            )
        )
    return out


def year_differences(
    session: Session, year: int, months: Sequence[int] | None = None
) -> list[CellDifference]:
    wanted = list(months) if months else list(range(1, 13))
    findings: list[CellDifference] = []
    for month in wanted:
        findings.extend(month_differences(session, year, month))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.records.compare_derived")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, action="append", dest="months")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.months:
        for month in args.months:
            if month < 1 or month > 12:
                print("month must be 1..12", file=sys.stderr)
                return 2
    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredError as error:
        print(error, file=sys.stderr)
        return 2
    try:
        with sessionmaker() as session:
            findings = year_differences(session, args.year, args.months)
            # Read-only: never leave a write hanging.
            session.rollback()
    except SQLAlchemyError as error:
        print(f"database error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    elif not findings:
        scope = f"{args.year}" if not args.months else f"{args.year} months {args.months}"
        print(f"OK: stored derived values match active records for {scope}.")
    else:
        print(f"{len(findings)} difference(s) (stored vs record-derived):")
        for item in findings:
            stored = "—" if item.stored is None else item.stored
            print(
                f"  {item.year}-{item.month:02d} {item.section}/{item.category}: "
                f"stored={stored} derived={item.derived} diff={item.difference:+d}"
            )
            if item.records:
                print(f"    records: {', '.join(item.records)}")
            else:
                print("    records: (none active in month)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
