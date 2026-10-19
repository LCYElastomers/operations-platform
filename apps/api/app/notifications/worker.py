"""Process pending notification outbox rows.

    python -m app.notifications.worker process [--limit N]

Intended for a host scheduler (cron) or an operator. Does not run inside the
API process by default; the API may also drain a few rows after a write via
BackgroundTasks when email is enabled.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.notifications.outbox import process_pending

logger = logging.getLogger(__name__)


def process(limit: int) -> int:
    settings = get_settings()
    if settings.database_url is None:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    sessionmaker = get_sessionmaker()
    with sessionmaker() as session:
        try:
            count = process_pending(session, limit=limit)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Notification worker failed")
            raise
    print(f"Processed {count} outbox row(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.notifications.worker")
    sub = parser.add_subparsers(dest="command", required=True)
    process_cmd = sub.add_parser("process", help="claim and deliver pending outbox rows")
    process_cmd.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    logging.basicConfig(level=get_settings().log_level)
    if args.command == "process":
        return process(args.limit)
    return 2


if __name__ == "__main__":
    sys.exit(main())
