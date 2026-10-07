import datetime as dt
import re
import uuid
from typing import Annotated, Any

from pydantic import AwareDatetime, BeforeValidator, ConfigDict, Field

from app.core.schemas import CamelModel
from app.safety.contacts.models import EARLIEST_DATE, MAX_DISPLAY_NAME_LENGTH


def _iso_date_only(value: Any) -> Any:
    """Accept "YYYY-MM-DD" only; timestamps, numbers, and other date formats are rejected."""
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise ValueError("expected a date as YYYY-MM-DD")


def _normalize_name(value: Any) -> Any:
    """Trim and collapse inner whitespace, so "Jo  Smith " and "Jo Smith" are one name."""
    if isinstance(value, str):
        return " ".join(value.split())
    return value


ProgramDate = Annotated[dt.date, BeforeValidator(_iso_date_only), Field(ge=EARLIEST_DATE)]
DisplayName = Annotated[
    str,
    BeforeValidator(_normalize_name),
    Field(strict=True, min_length=1, max_length=MAX_DISPLAY_NAME_LENGTH),
]
SupervisorId = Annotated[int, Field(strict=True, ge=1)]
Flag = Annotated[bool, Field(strict=True)]


# Supervisors ---------------------------------------------------------------------


class SupervisorInput(CamelModel):
    """A supervisor on the program list. Every field is required, so active and
    participation eligibility are always set explicitly. An inactive supervisor
    needs an end date (``effectiveTo``)."""

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName
    active: Flag
    participation_eligible: Flag
    effective_from: ProgramDate
    effective_to: ProgramDate | None


class SupervisorUpdate(SupervisorInput):
    """Replaces every field. ``expected_updated_at`` is the ``updatedAt`` the
    client loaded; the update is refused if the supervisor changed since."""

    expected_updated_at: AwareDatetime


class SupervisorOut(CamelModel):
    id: int
    display_name: str
    active: bool
    participation_eligible: bool
    effective_from: dt.date
    effective_to: dt.date | None
    has_contacts: bool = Field(description="Supervisors with contacts cannot be deleted.")
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


class SupervisorListResponse(CamelModel):
    """Every supervisor, active and inactive, in alphabetical order."""

    supervisors: list[SupervisorOut]
    can_edit: bool


# Contacts ------------------------------------------------------------------------


class ContactInput(CamelModel):
    """One contact credited to one supervisor on one date."""

    model_config = ConfigDict(extra="forbid")

    contact_date: ProgramDate
    supervisor_id: SupervisorId


class ContactCreate(ContactInput):
    request_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Client-generated key for this submission. Resubmitting the same key "
            "returns the contact already recorded instead of adding another."
        ),
    )


class ContactUpdate(ContactInput):
    """Replaces the date and supervisor. ``expected_updated_at`` is the
    ``updatedAt`` the client loaded; the update is refused if the contact
    changed since."""

    expected_updated_at: AwareDatetime


class ContactOut(CamelModel):
    id: int
    contact_date: dt.date
    supervisor_id: int
    supervisor_name: str
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


class ContactListResponse(CamelModel):
    """Newest contact date first, then newest entry first."""

    contacts: list[ContactOut]
    total_matching: int
    can_edit: bool


# Summaries -----------------------------------------------------------------------


class Participation(CamelModel):
    """Eligible supervisors with at least one contact in the month, out of the
    supervisors eligible for the month."""

    participating: int
    eligible: int
    rate: float | None = Field(description="participating / eligible; null when none are eligible.")


class SupervisorCount(CamelModel):
    supervisor_id: int
    display_name: str
    active: bool
    contacts: int


class ContactSummaryResponse(CamelModel):
    """Counts for a reporting period: a year, or one month of it."""

    year: int
    month: int | None
    contacts: int
    participation: Participation | None = Field(
        description="Only for a single month; participation is a monthly measure."
    )
    supervisors: list[SupervisorCount] = Field(
        description=(
            "Alphabetical: active supervisors and any supervisor with contacts in the period."
        )
    )


class DashboardMonth(CamelModel):
    month: int
    contacts: int | None = Field(description="Null for months that have not started yet.")
    participation: Participation | None = Field(
        description="Null for months that have not started yet."
    )


class DashboardSupervisor(CamelModel):
    supervisor_id: int
    display_name: str
    active: bool
    monthly: list[int | None] = Field(
        description="12 entries, January first; null for months that have not started yet."
    )
    total: int


class ContactDashboardResponse(CamelModel):
    year: int
    through_month: int = Field(
        description="Last month of the year that has started (0-12). Later months are null."
    )
    contacts: int
    months: list[DashboardMonth]
    supervisors: list[DashboardSupervisor] = Field(
        description=(
            "Alphabetical: supervisors in the program during the year or with contacts in it."
        )
    )
    years_with_data: list[int]
