"""Operator commands for sign-in administration, run on the server:

    python -m app.auth.cli bootstrap-admin --email EMAIL --name NAME [--base-url URL]
    python -m app.auth.cli password-link --email EMAIL [--base-url URL]

``bootstrap-admin`` creates the first administrator (role ADMIN) and prints a
one-time link to set their password. It refuses once any active user can
manage users and roles, so it cannot be used to add administrators later; do
that in the application.

``password-link`` recovers access when no administrator can sign in: it prints
a new one-time link for an existing active user.

Both need shell access to the server and its database settings. The link is
printed to this terminal only; it is not logged. Nobody's password is ever
shown, stored in settings or passed on the command line.
"""

import argparse
import datetime as dt
import sys
import uuid

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.auth import service
from app.auth.admin import administrator_exists, lock_administration
from app.auth.models import User, UserRole
from app.auth.roles import ADMIN_CODE
from app.auth.schemas import Email, Name
from app.core.config import get_settings
from app.db.session import get_sessionmaker

CLI_ACTOR = "operator-cli"


def _link(base_url: str | None, token: str) -> str:
    # The token travels in the fragment, which browsers do not send to servers or logs.
    return f"{(base_url or '').rstrip('/')}/setup-password#token={token}"


def bootstrap_admin(db: Session, email: str, name: str, base_url: str | None) -> int:
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    lock_administration(db)
    if administrator_exists(db):
        print(
            "Refused: an active administrator already exists. Add users in the application.",
            file=sys.stderr,
        )
        return 1
    normalized = service.normalize_email(email)
    if db.scalar(select(User.id).where(User.email == normalized)) is not None:
        print("Refused: a user with this email already exists.", file=sys.stderr)
        return 1
    user = User(
        id=uuid.uuid4(),
        email=normalized,
        name=name.strip(),
        status="active",
        created_at=now,
        created_by=CLI_ACTOR,
        updated_at=now,
        updated_by=CLI_ACTOR,
    )
    db.add(user)
    db.flush()
    db.execute(
        insert(UserRole),
        [
            {
                "user_id": user.id,
                "role_code": ADMIN_CODE,
                "assigned_at": now,
                "assigned_by": CLI_ACTOR,
            }
        ],
    )
    record_changes(
        db,
        actor_id=CLI_ACTOR,
        change_set_id=uuid.uuid4(),
        occurred_at=now,
        changes=[
            AuditChange(
                "create",
                service.USER_ENTITY,
                service.user_key(user.id),
                None,
                {
                    "email": user.email,
                    "name": user.name,
                    "image": None,
                    "status": "active",
                    "roles": [ADMIN_CODE],
                },
            )
        ],
    )
    link = service.issue_password_link(
        db, user, "setup", issued_by=CLI_ACTOR, settings=settings, now=now
    )
    db.commit()
    print(f"Created administrator {user.name} ({user.email}).")
    print(
        "Send them this one-time link to set their password "
        f"(valid until {link.expires_at:%Y-%m-%d %H:%M} UTC):"
    )
    print(_link(base_url, link.token))
    return 0


def password_link(db: Session, email: str, base_url: str | None) -> int:
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    user = db.scalar(select(User).where(User.email == service.normalize_email(email)))
    if user is None or user.status != "active":
        print("Refused: no active user has this email.", file=sys.stderr)
        return 1
    purpose = "reset" if user.password_hash is not None else "setup"
    link = service.issue_password_link(
        db, user, purpose, issued_by=CLI_ACTOR, settings=settings, now=now
    )
    db.commit()
    print(f"One-time link for {user.name} (valid until {link.expires_at:%Y-%m-%d %H:%M} UTC):")
    print(_link(base_url, link.token))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-admin", help="create the first administrator")
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--name", required=True)
    bootstrap.add_argument("--base-url", help="e.g. https://operations.example.com")
    recover = commands.add_parser("password-link", help="new password link for a user")
    recover.add_argument("--email", required=True)
    recover.add_argument("--base-url")
    args = parser.parse_args(argv)
    try:
        email = TypeAdapter(Email).validate_python(args.email)
        name = (
            TypeAdapter(Name).validate_python(args.name)
            if args.command == "bootstrap-admin"
            else ""
        )
    except ValidationError:
        print("Refused: invalid email or name.", file=sys.stderr)
        return 2
    with get_sessionmaker()() as db:
        if args.command == "bootstrap-admin":
            return bootstrap_admin(db, email, name, args.base_url)
        return password_link(db, email, args.base_url)


if __name__ == "__main__":
    sys.exit(main())
