"""Read-only report of active records with overlapping injury outcomes.

    python -m app.safety.records.injury_outcome_report
    python -m app.safety.records.injury_outcome_report --json

Does not modify records. Lists incidents that still carry more than one of
Recordable Injury, Lost Time Injury, and Restricted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety.trir_eligibility import overlapping_injury_outcome_records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.records.injury_outcome_report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredError as error:
        print(error, file=sys.stderr)
        return 2
    try:
        with sessionmaker() as session:
            rows = overlapping_injury_outcome_records(session)
            session.rollback()
    except SQLAlchemyError as error:
        print(f"database error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(rows, indent=2))
    elif not rows:
        print("OK: no active records with overlapping injury outcomes.")
    else:
        print(f"{len(rows)} active record(s) with more than one injury outcome:")
        for row in rows:
            outcomes = ", ".join(row["outcomes"])  # type: ignore[arg-type]
            print(
                f"  {row['incidentNumber']} ({row['incidentDate']}): {outcomes}"
            )
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
