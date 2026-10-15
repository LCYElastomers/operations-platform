"""Safety import runs (migration 0016).

One row per ``plan`` or ``apply`` of a Safety import, written whether it
succeeds or not: which importer, which reviewed file (name and SHA-256), who
started it, when, the outcome and its counts. A run is durable history only;
the imported records themselves are written to their own permanent tables in
the importer's transaction, and ``change_set_id`` links an applied run to its
audit events (``core.audit_events``). A count is null when the importer does
not report it, distinct from 0.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.safety.models import SAFETY_SCHEMA

IMPORTERS = (
    "monthly_metrics",
    "behavior",
    "performance",
    "trir_history",
    "incident_records",
    "psm_pha",
)
COMMANDS = ("plan", "apply")
# running: started, no outcome yet (or the process died). planned: a plan that
# could be applied; blocked: a plan or apply refused by the plan's checks.
STATUSES = ("running", "planned", "blocked", "applied", "nothing_to_apply", "failed")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ImportRun(Base):
    __tablename__ = "import_runs"
    __table_args__ = (
        UniqueConstraint("run_id"),
        CheckConstraint(f"importer IN ({_in(IMPORTERS)})", name="importer"),
        CheckConstraint(f"command IN ({_in(COMMANDS)})", name="command"),
        CheckConstraint(f"status IN ({_in(STATUSES)})", name="status"),
        CheckConstraint(
            "status IN ('running', 'planned', 'blocked', 'failed') OR command = 'apply'",
            name="apply_outcome",
        ),
        CheckConstraint("(status = 'running') = (finished_at IS NULL)", name="finished"),
        CheckConstraint("status = 'applied' OR change_set_id IS NULL", name="change_set"),
        CheckConstraint(
            "inserted_count >= 0 AND updated_count >= 0 AND skipped_count >= 0 "
            "AND conflict_count >= 0 AND failed_count >= 0",
            name="counts",
        ),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_sha256"),
        CheckConstraint("btrim(source_file_name) <> ''", name="source_file_name"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    importer: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    source_file_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    initiated_by: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    inserted_count: Mapped[int | None] = mapped_column(Integer)
    updated_count: Mapped[int | None] = mapped_column(Integer)
    skipped_count: Mapped[int | None] = mapped_column(Integer)
    conflict_count: Mapped[int | None] = mapped_column(Integer)
    failed_count: Mapped[int | None] = mapped_column(Integer)
    # Validation errors, conflicts and blocking reasons; never credentials.
    messages: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
