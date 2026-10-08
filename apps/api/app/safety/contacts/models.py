"""Supervisor Safety Contacts: the program's supervisor list and one row per contact.

RETIRED. The function has no endpoints, pages or permissions any more. The
tables (migration 0005) and their rows are kept unchanged as a historical
record; these models remain only so the schema stays described by the
metadata. Nothing reads or writes them, and no further data is imported.

A contact is one safety contact credited to one supervisor on one date. Every
count (per month, per supervisor, year to date, participation) is counted from
these rows and never stored.

Supervisors are a list owned by this program, not platform users or an
employee directory. A later revision may add a nullable link to an
authenticated user; display names stay the program's own record.

Program targets (e.g. contacts per month) are not stored in v1. When they are
introduced they belong in their own table keyed by year/month, never on the
supervisor rows.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.safety.models import SAFETY_SCHEMA

EARLIEST_DATE = dt.date(2000, 1, 1)
MAX_DISPLAY_NAME_LENGTH = 100


class ContactSupervisor(Base):
    """A supervisor on the program list.

    ``active`` controls whether new contacts can be credited. ``effective_from``
    and ``effective_to`` bound the months the supervisor counts toward
    participation; ``participation_eligible`` excludes them from it entirely.
    An inactive supervisor always has an end date, so they stop counting in
    later months but remain in historical figures.
    """

    __tablename__ = "contact_supervisors"
    __table_args__ = (
        # Stored trimmed with single inner spaces; uniqueness ignores case.
        CheckConstraint(
            "display_name = btrim(display_name) AND display_name <> '' "
            f"AND char_length(display_name) <= {MAX_DISPLAY_NAME_LENGTH}",
            name="display_name",
        ),
        CheckConstraint(
            f"effective_from >= DATE '{EARLIEST_DATE.isoformat()}'", name="effective_from"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="effective_period"
        ),
        CheckConstraint("active OR effective_to IS NOT NULL", name="inactive_has_end"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    participation_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effective_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class SupervisorSafetyContact(Base):
    __tablename__ = "supervisor_safety_contacts"
    __table_args__ = (
        CheckConstraint(f"contact_date >= DATE '{EARLIEST_DATE.isoformat()}'", name="contact_date"),
        # Client-generated key of the submitting tap; a resubmission returns the
        # first record instead of crediting a second contact.
        UniqueConstraint("request_id"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    contact_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # No cascade: a supervisor with contacts cannot be deleted.
    supervisor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            ContactSupervisor.id,
            name="fk_supervisor_safety_contacts_supervisor",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


Index(
    "uq_contact_supervisors_display_name",
    func.lower(ContactSupervisor.display_name),
    unique=True,
)
Index("ix_supervisor_safety_contacts_contact_date", SupervisorSafetyContact.contact_date)
Index("ix_supervisor_safety_contacts_supervisor_id", SupervisorSafetyContact.supervisor_id)
