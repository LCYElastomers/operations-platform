"""ReportDefinition: what a dashboard or register declares to be exportable.

A module declares its reports (key, title, permissions, filters, period modes
and a ``build`` function that reads its data through its own repository and
services). The export endpoint (``app.reports.router``) does everything else:
authentication, permission checks, validation, rendering and auditing.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.authorization import UserPrincipal
from app.core.permissions import Permission
from app.reports.model import Chart, Kpi, Table
from app.reports.period import Period

ReportFormat = Literal["pdf", "xlsx"]


class ReportInputError(ValueError):
    """The request is valid in form but cannot be reported (answered with 422)."""


class NoFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class ReportContext:
    """The normalized request every builder reads: the same period and filters
    as the screen, the site date and the signed-in user."""

    session: Session
    principal: UserPrincipal
    period: Period
    filters: BaseModel
    today: dt.date
    now: dt.datetime


@dataclass(frozen=True)
class ReportContent:
    filters: list[tuple[str, str]]
    """Human-readable applied filters, e.g. ("Department", "Production")."""
    kpis: list[Kpi] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    subtitle: str = ""
    period_label: str | None = None
    """Overrides the period's label when the data covers a narrower span
    (e.g. a summary that runs through the latest month with records)."""
    filename_period: str | None = None


@dataclass(frozen=True)
class ReportDefinition:
    key: str
    title: str
    module: str
    filename: str
    """The middle of the file name: ``Operations-Platform_<filename>_<period>.pdf``."""
    view_permissions: tuple[Permission, ...]
    export_permission: Permission
    build: Callable[[ReportContext], ReportContent]
    filters: type[BaseModel] = NoFilters
    formats: tuple[ReportFormat, ...] = ("pdf", "xlsx")
    period_modes: frozenset[str] | None = None
    """The period modes this report accepts; None accepts all."""

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (*self.view_permissions, self.export_permission)
