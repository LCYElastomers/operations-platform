"""Database access for Supervisor Safety Contacts."""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sqlalchemy import Select, delete, exists, extract, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.safety.contacts.models import ContactSupervisor, SupervisorSafetyContact

DISPLAY_NAME_INDEX = "uq_contact_supervisors_display_name"
REQUEST_ID_CONSTRAINT = "uq_supervisor_safety_contacts_request_id"
SUPERVISOR_FOREIGN_KEY = "fk_supervisor_safety_contacts_supervisor"

# "share" stops the supervisor being changed or deleted while a contact is
# credited to them; "update" is for changing the supervisor itself.
SupervisorLock = Literal["share", "update"]


class DuplicateDisplayNameError(ValueError):
    """Another supervisor already has this name (ignoring case)."""


class SupervisorReferencedError(RuntimeError):
    """Contacts are credited to the supervisor, so it cannot be deleted."""


@dataclass(frozen=True)
class SupervisorValues:
    display_name: str
    active: bool
    participation_eligible: bool
    effective_from: dt.date
    effective_to: dt.date | None


@dataclass(frozen=True)
class SupervisorRecord:
    id: int
    values: SupervisorValues
    has_contacts: bool
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


@dataclass(frozen=True)
class ContactValues:
    contact_date: dt.date
    supervisor_id: int


@dataclass(frozen=True)
class ContactRecord:
    id: int
    values: ContactValues
    supervisor_name: str
    request_id: uuid.UUID | None
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


@dataclass(frozen=True)
class ContactFilter:
    contact_from: dt.date | None = None
    # Inclusive.
    contact_to: dt.date | None = None
    supervisor_id: int | None = None


@dataclass(frozen=True)
class CountRow:
    """Number of contacts credited to one supervisor in one month."""

    month: int
    supervisor_id: int
    count: int


class ContactRepository(Protocol):
    def supervisors(self) -> list[SupervisorRecord]:
        """Every supervisor (active and inactive), alphabetical."""
        ...

    def get_supervisor(
        self, supervisor_id: int, *, lock: SupervisorLock | None = None
    ) -> SupervisorRecord | None: ...

    def insert_supervisor(self, values: SupervisorValues, *, actor_id: str, at: dt.datetime) -> int:
        """Raises DuplicateDisplayNameError if the name is taken."""
        ...

    def update_supervisor(
        self, supervisor_id: int, values: SupervisorValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        """Raises DuplicateDisplayNameError if the name is taken."""
        ...

    def delete_supervisor(self, supervisor_id: int) -> None:
        """Raises SupervisorReferencedError if contacts are credited to the supervisor."""
        ...

    def contacts_outside(
        self, supervisor_id: int, effective_from: dt.date, effective_to: dt.date | None
    ) -> int:
        """How many of the supervisor's contacts fall outside the period."""
        ...

    def search(
        self, criteria: ContactFilter, *, limit: int, offset: int
    ) -> tuple[list[ContactRecord], int]:
        """One page of matching contacts, newest first, and the total match count."""
        ...

    def get(self, contact_id: int, *, for_update: bool = False) -> ContactRecord | None: ...

    def get_by_request(self, request_id: uuid.UUID) -> ContactRecord | None: ...

    def insert(
        self,
        values: ContactValues,
        *,
        request_id: uuid.UUID | None,
        actor_id: str,
        at: dt.datetime,
    ) -> int | None:
        """The new contact's id, or None if ``request_id`` was already recorded."""
        ...

    def update(
        self, contact_id: int, values: ContactValues, *, actor_id: str, at: dt.datetime
    ) -> None: ...

    def delete(self, contact_id: int) -> None: ...

    def counts(self, criteria: ContactFilter) -> list[CountRow]: ...

    def years_with_contacts(self) -> list[int]: ...

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def _filtered(statement: Select[Any], criteria: ContactFilter) -> Select[Any]:
    c = SupervisorSafetyContact
    if criteria.contact_from is not None:
        statement = statement.where(c.contact_date >= criteria.contact_from)
    if criteria.contact_to is not None:
        statement = statement.where(c.contact_date <= criteria.contact_to)
    if criteria.supervisor_id is not None:
        statement = statement.where(c.supervisor_id == criteria.supervisor_id)
    return statement


def _is_duplicate_name(error: IntegrityError) -> bool:
    return DISPLAY_NAME_INDEX in str(error.orig)


class DatabaseContactRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # Supervisors

    def _supervisor_rows(self) -> Select[Any]:
        s = SupervisorSafetyContact
        has_contacts = exists().where(s.supervisor_id == ContactSupervisor.id)
        # populate_existing: always return the stored row, never a stale session copy.
        return select(ContactSupervisor, has_contacts.label("has_contacts")).execution_options(
            populate_existing=True
        )

    @staticmethod
    def _supervisor(row: ContactSupervisor, has_contacts: bool) -> SupervisorRecord:
        return SupervisorRecord(
            id=row.id,
            values=SupervisorValues(
                display_name=row.display_name,
                active=row.active,
                participation_eligible=row.participation_eligible,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
            ),
            has_contacts=has_contacts,
            created_at=row.created_at,
            created_by=row.created_by,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )

    def supervisors(self) -> list[SupervisorRecord]:
        s = ContactSupervisor
        rows = self._session.execute(
            self._supervisor_rows().order_by(func.lower(s.display_name), s.id)
        ).all()
        return [self._supervisor(*row) for row in rows]

    def get_supervisor(
        self, supervisor_id: int, *, lock: SupervisorLock | None = None
    ) -> SupervisorRecord | None:
        statement = self._supervisor_rows().where(ContactSupervisor.id == supervisor_id)
        if lock == "share":
            statement = statement.with_for_update(of=ContactSupervisor, read=True, key_share=True)
        elif lock == "update":
            statement = statement.with_for_update(of=ContactSupervisor)
        row = self._session.execute(statement).one_or_none()
        return None if row is None else self._supervisor(*row)

    def insert_supervisor(self, values: SupervisorValues, *, actor_id: str, at: dt.datetime) -> int:
        try:
            supervisor_id = self._session.scalar(
                insert(ContactSupervisor)
                .values(
                    **vars(values),
                    created_at=at,
                    created_by=actor_id,
                    updated_at=at,
                    updated_by=actor_id,
                )
                .returning(ContactSupervisor.id)
            )
        except IntegrityError as error:
            if _is_duplicate_name(error):
                raise DuplicateDisplayNameError(values.display_name) from error
            raise
        assert supervisor_id is not None  # noqa: S101 - INSERT ... RETURNING yields the key
        return supervisor_id

    def update_supervisor(
        self, supervisor_id: int, values: SupervisorValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        try:
            self._session.execute(
                update(ContactSupervisor)
                .where(ContactSupervisor.id == supervisor_id)
                .values(**vars(values), updated_at=at, updated_by=actor_id)
                .execution_options(synchronize_session=False)
            )
        except IntegrityError as error:
            if _is_duplicate_name(error):
                raise DuplicateDisplayNameError(values.display_name) from error
            raise

    def delete_supervisor(self, supervisor_id: int) -> None:
        try:
            self._session.execute(
                delete(ContactSupervisor)
                .where(ContactSupervisor.id == supervisor_id)
                .execution_options(synchronize_session=False)
            )
        except IntegrityError as error:
            if SUPERVISOR_FOREIGN_KEY in str(error.orig):
                raise SupervisorReferencedError(supervisor_id) from error
            raise

    def contacts_outside(
        self, supervisor_id: int, effective_from: dt.date, effective_to: dt.date | None
    ) -> int:
        c = SupervisorSafetyContact
        outside = c.contact_date < effective_from
        if effective_to is not None:
            outside = or_(outside, c.contact_date > effective_to)
        count = self._session.scalar(
            select(func.count()).where(c.supervisor_id == supervisor_id, outside)
        )
        return count or 0

    # Contacts

    def _records(self) -> Select[Any]:
        s = ContactSupervisor
        return (
            select(SupervisorSafetyContact, s.display_name)
            .join(s, s.id == SupervisorSafetyContact.supervisor_id)
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _record(contact: SupervisorSafetyContact, supervisor_name: str) -> ContactRecord:
        return ContactRecord(
            id=contact.id,
            values=ContactValues(
                contact_date=contact.contact_date, supervisor_id=contact.supervisor_id
            ),
            supervisor_name=supervisor_name,
            request_id=contact.request_id,
            created_at=contact.created_at,
            created_by=contact.created_by,
            updated_at=contact.updated_at,
            updated_by=contact.updated_by,
        )

    def search(
        self, criteria: ContactFilter, *, limit: int, offset: int
    ) -> tuple[list[ContactRecord], int]:
        c = SupervisorSafetyContact
        total = self._session.scalar(_filtered(select(func.count()).select_from(c), criteria))
        rows = self._session.execute(
            _filtered(self._records(), criteria)
            .order_by(c.contact_date.desc(), c.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [self._record(*row) for row in rows], total or 0

    def get(self, contact_id: int, *, for_update: bool = False) -> ContactRecord | None:
        statement = self._records().where(SupervisorSafetyContact.id == contact_id)
        if for_update:
            statement = statement.with_for_update(of=SupervisorSafetyContact)
        row = self._session.execute(statement).one_or_none()
        return None if row is None else self._record(*row)

    def get_by_request(self, request_id: uuid.UUID) -> ContactRecord | None:
        statement = self._records().where(SupervisorSafetyContact.request_id == request_id)
        row = self._session.execute(statement).one_or_none()
        return None if row is None else self._record(*row)

    def insert(
        self,
        values: ContactValues,
        *,
        request_id: uuid.UUID | None,
        actor_id: str,
        at: dt.datetime,
    ) -> int | None:
        return self._session.scalar(
            insert(SupervisorSafetyContact)
            .values(
                **vars(values),
                request_id=request_id,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
            .on_conflict_do_nothing(constraint=REQUEST_ID_CONSTRAINT)
            .returning(SupervisorSafetyContact.id)
        )

    def update(
        self, contact_id: int, values: ContactValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self._session.execute(
            update(SupervisorSafetyContact)
            .where(SupervisorSafetyContact.id == contact_id)
            .values(**vars(values), updated_at=at, updated_by=actor_id)
            .execution_options(synchronize_session=False)
        )

    def delete(self, contact_id: int) -> None:
        self._session.execute(
            delete(SupervisorSafetyContact)
            .where(SupervisorSafetyContact.id == contact_id)
            .execution_options(synchronize_session=False)
        )

    def counts(self, criteria: ContactFilter) -> list[CountRow]:
        c = SupervisorSafetyContact
        month = extract("month", c.contact_date).label("month")
        rows = self._session.execute(
            _filtered(
                select(month, c.supervisor_id, func.count().label("count")), criteria
            ).group_by(month, c.supervisor_id)
        ).all()
        return [
            CountRow(month=int(row.month), supervisor_id=row.supervisor_id, count=row.count)
            for row in rows
        ]

    def years_with_contacts(self) -> list[int]:
        year = extract("year", SupervisorSafetyContact.contact_date)
        years = self._session.scalars(select(year).distinct().order_by(year)).all()
        return [int(value) for value in years]

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None:
        record_changes(
            self._session,
            actor_id=actor_id,
            change_set_id=change_set_id,
            occurred_at=at,
            changes=changes,
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
