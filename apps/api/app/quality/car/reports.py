"""CAR Dashboard and CAR Register exports.

Both read the reports through the same ``car_filter`` and repository search as
``GET /quality/cars`` and ``/quality/cars/dashboard``; the period is the
request-date range of the screen's period filter.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.permissions import Permission
from app.quality.car import dashboard, service
from app.quality.car.reference import (
    CAR_STATUSES,
    DEPARTMENTS,
    EFFECTIVENESS_RESULTS,
    LEGACY_DEPARTMENTS,
    ROOT_CAUSE_CATEGORIES,
    SOURCES,
)
from app.quality.car.repository import CarRepository
from app.quality.car.router import _due_soon_days, car_filter
from app.quality.car.schemas import CarDashboardResponse, CarListItemOut, CountOut
from app.reports.definitions import ReportContent, ReportContext, ReportDefinition
from app.reports.model import Chart, Column, Kpi, Series, Table, Value

MODULE = "Quality · Corrective Action Reports"
COLORS = {"open": "#2563eb", "closed": "#059669", "past_due": "#dc2626", "cost": "#ea580c"}

Code = Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,50}$")]
Name = Annotated[str, StringConstraints(max_length=200)]


class CarDashboardFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    department: list[Code] = Field(default_factory=list, max_length=20)
    source: list[Code] = Field(default_factory=list, max_length=20)
    assigned_to: Name | None = Field(default=None, alias="assignedTo")


class CarRegisterFilters(CarDashboardFilters):
    status: list[Code] = Field(default_factory=list, max_length=5)
    root_cause: list[Code] = Field(default_factory=list, max_length=20, alias="rootCause")
    effectiveness: list[Code] = Field(default_factory=list, max_length=5)
    mine: bool = False
    past_due: bool = Field(default=False, alias="pastDue")
    due_soon: bool = Field(default=False, alias="dueSoon")
    repeat: bool | None = None
    search: Name | None = None
    sort: Literal["newest", "oldest"] = "newest"


def _label(code: str, *maps: dict[str, str]) -> str:
    if code == "not_recorded":
        return "Not recorded"
    for labels in maps:
        if code in labels:
            return labels[code]
    return code


def _codes(name: str, codes: list[str], *maps: dict[str, str]) -> list[tuple[str, str]]:
    return [(name, ", ".join(_label(c, *maps) for c in codes))] if codes else []


def _dashboard_filters(f: CarDashboardFilters) -> list[tuple[str, str]]:
    return [
        *_codes("Department", f.department, DEPARTMENTS, LEGACY_DEPARTMENTS),
        *_codes("Source", f.source, SOURCES),
        *([("Assigned to", f.assigned_to)] if f.assigned_to else []),
    ]


def _register_filters(f: CarRegisterFilters, ctx: ReportContext) -> list[tuple[str, str]]:
    applied = [
        *([("Search", f.search)] if f.search else []),
        *_codes("Status", f.status, CAR_STATUSES),
        *_dashboard_filters(f),
        *_codes("Root cause", f.root_cause, ROOT_CAUSE_CATEGORIES),
        *_codes("Effectiveness", f.effectiveness, EFFECTIVENESS_RESULTS),
    ]
    if f.mine:
        applied.append(("Assigned to me", ctx.principal.display_name or "Yes"))
    if f.past_due:
        applied.append(("Past due", "Yes"))
    if f.due_soon:
        applied.append(("Due soon", f"Within {_due_soon_days()} days"))
    if f.repeat is not None:
        applied.append(("Previous / repeat", "Yes" if f.repeat else "No"))
    applied.append(
        (
            "Sort",
            "Request date, oldest first" if f.sort == "oldest" else "Request date, newest first",
        )
    )
    return applied


def _counts(title: str, counts: list[CountOut], *, kind: str = "bar", color: str) -> Chart:
    present = [c for c in counts if c.count > 0]
    return Chart(
        title,
        [c.label for c in present],
        [Series("CARs", [c.count for c in present], color)],
        kind=kind,  # type: ignore[arg-type]
        x_label="Category",
    )


def _yes_no(value: bool | None) -> str | None:
    return None if value is None else ("Yes" if value else "No")


REGISTER_COLUMNS = [
    Column("CAR Number", "text", 14),
    Column("Request Date", "date", 12),
    Column("Subject", "text", 40),
    Column("Department", "text", 18),
    Column("Source", "text", 18),
    Column("Requested By", "text", 18),
    Column("Assigned To", "text", 18),
    Column("Due Date", "date", 12),
    Column("CAR Status", "text", 12),
    Column("Date Closed", "date", 12),
    Column("Root Cause", "text", 18),
    Column("Effectiveness", "text", 14),
    Column("Repeat", "text", 8),
    Column("Days Open", "int", 10),
    Column("Past Due", "text", 9),
    Column("Actions Complete", "int", 10),
    Column("Actions Total", "int", 10),
    Column("Actions Overdue", "int", 10),
    Column("Cost Impact", "money", 14),
]

PDF_COLUMNS = [0, 1, 2, 3, 6, 7, 8, 11, 13, 18]


def _register_row(car: CarListItemOut) -> list[Value]:
    return [
        car.car_number,
        car.request_date,
        car.subject,
        car.department_label,
        car.source_label,
        car.requested_by,
        car.assigned_to,
        car.due_date,
        car.status_label,
        car.date_closed,
        car.root_cause_label,
        car.effectiveness_label,
        _yes_no(car.previous_occurrence),
        car.days_open,
        "Yes" if car.past_due else "No",
        car.actions.complete,
        car.actions.total,
        car.actions.overdue,
        car.total_cost,
    ]


def _kpis(data: CarDashboardResponse) -> list[Kpi]:
    k = data.kpis
    status_note = (
        f" · {k.status_not_recorded} imported with no status" if k.status_not_recorded else ""
    )
    return [
        Kpi("CARs in selection", k.total),
        Kpi("Open CARs", k.open, caption=f"Not closed{status_note}"),
        Kpi("Past due", k.past_due, caption="Not closed, due date passed"),
        Kpi("Due soon", k.due_soon, caption=f"Due within {data.due_soon_days} days"),
        Kpi(
            "Awaiting effectiveness",
            k.awaiting_effectiveness,
            caption="All actions complete, not yet reviewed",
        ),
        Kpi("Closed YTD", k.closed_ytd, caption=f"Closed in {data.year}"),
        Kpi("Corrective actions overdue", k.actions_overdue),
        Kpi(
            "Cost impact",
            data.cost.total,
            "money",
            caption=f"{data.cost.with_cost} CARs with a cost entered; "
            f"{data.cost.without_cost} have none (not counted as $0)",
        ),
    ]


def _charts(data: CarDashboardResponse) -> list[Chart]:
    months = [f"{m.year}-{m.month:02d}" for m in data.trend]
    cost = sorted(data.cost.by_department, key=lambda d: d.total, reverse=True)
    return [
        _counts("CARs by status", data.by_status, color=COLORS["open"]),
        Chart(
            "Opened vs closed, last 12 months",
            months,
            [
                Series("Opened", [m.opened for m in data.trend], COLORS["open"]),
                Series("Closed", [m.closed for m in data.trend], COLORS["closed"]),
            ],
            x_label="Month",
            y_label="CARs",
        ),
        Chart(
            "Aging of CARs not closed",
            [b.label for b in data.aging],
            [Series("CARs", [b.count for b in data.aging], COLORS["past_due"])],
            x_label="Days since request",
            description="Days since the request date.",
        ),
        _counts("Effectiveness review", data.effectiveness, color=COLORS["closed"]),
        _counts("CARs by department", data.by_department, kind="hbar", color=COLORS["open"]),
        _counts("CARs by source", data.by_source, kind="hbar", color=COLORS["open"]),
        _counts("CARs by root cause", data.by_root_cause, kind="hbar", color="#64748b"),
        _counts("Repeat occurrences", data.repeat, color=COLORS["cost"]),
        Chart(
            "Cost impact by department",
            [d.label for d in cost],
            [Series("Cost impact ($)", [d.total for d in cost], COLORS["cost"])],
            kind="hbar",
            value_type="money",
            x_label="Department",
            description="CARs with no cost entered are not counted as $0.",
        ),
    ]


def build_dashboard(ctx: ReportContext) -> ReportContent:
    f = ctx.filters
    assert isinstance(f, CarDashboardFilters)  # noqa: S101 - set by the definition
    repository = CarRepository(ctx.session)
    criteria = car_filter(
        date_from=ctx.period.start,
        date_to=ctx.period.end,
        department=f.department,
        source=f.source,
        assigned_to=f.assigned_to,
    )
    rows, _ = repository.search(criteria)
    days = _due_soon_days()
    data = dashboard.summary(rows, today=ctx.today, due_soon_days=days)
    cars = [service.list_item_out(r, ctx.today, days) for r in rows]
    past_due = [c for c in cars if c.past_due]
    repeat = [[r.car_number, r.subject, r.previous_car] for r in data.repeat_cars]
    return ReportContent(
        filters=_dashboard_filters(f),
        subtitle="CARs requested in the period (by request date)",
        kpis=_kpis(data),
        charts=_charts(data),
        tables=[
            Table(
                "Past-due CARs",
                REGISTER_COLUMNS,
                [_register_row(c) for c in past_due],
                description="Not closed, with a due date before today.",
                sheet="Past Due",
                pdf_columns=PDF_COLUMNS,
                pdf_row_limit=200,
            ),
            Table(
                "Repeat CARs",
                [
                    Column("CAR Number", "text", 14),
                    Column("Subject", "text", 60),
                    Column("Previous CAR", "text", 16),
                ],
                repeat,
                description="Marked as a previous occurrence of the same problem.",
                sheet="Repeat CARs",
            ),
            Table(
                "CARs",
                REGISTER_COLUMNS,
                [_register_row(c) for c in cars],
                sheet="CARs",
                in_pdf=False,
            ),
        ],
    )


def build_register(ctx: ReportContext) -> ReportContent:
    f = ctx.filters
    assert isinstance(f, CarRegisterFilters)  # noqa: S101 - set by the definition
    repository = CarRepository(ctx.session)
    criteria = car_filter(
        date_from=ctx.period.start,
        date_to=ctx.period.end,
        car_status=f.status,
        department=f.department,
        source=f.source,
        root_cause=f.root_cause,
        effectiveness=f.effectiveness,
        assigned_to=f.assigned_to,
        mine_of=ctx.principal if f.mine else None,
        past_due=f.past_due,
        due_soon=f.due_soon,
        repeat=f.repeat,
        search=f.search,
    )
    rows, total = repository.search(criteria, oldest_first=f.sort == "oldest")
    days = _due_soon_days()
    data = dashboard.summary(rows, today=ctx.today, due_soon_days=days)
    cars = [service.list_item_out(r, ctx.today, days) for r in rows]
    k = data.kpis
    return ReportContent(
        filters=_register_filters(f, ctx),
        kpis=[
            Kpi("Matching CARs", total),
            Kpi("Open", k.open),
            Kpi("Past due", k.past_due),
            Kpi("Due soon", k.due_soon, caption=f"Due within {days} days"),
            Kpi("Closed", total - k.open),
            Kpi(
                "Cost impact",
                data.cost.total,
                "money",
                caption="Sum of entered costs; CARs with none are not counted as $0",
            ),
        ],
        tables=[
            Table(
                "CAR Register",
                REGISTER_COLUMNS,
                [_register_row(c) for c in cars],
                sheet="CAR Register",
            )
        ],
    )


DASHBOARD = ReportDefinition(
    key="car-dashboard",
    title="CAR Dashboard",
    module=MODULE,
    filename="CAR-Dashboard",
    view_permissions=(Permission.CAR_VIEW, Permission.QUALITY_DASHBOARD_VIEW),
    export_permission=Permission.CAR_EXPORT,
    filters=CarDashboardFilters,
    build=build_dashboard,
)

REGISTER = ReportDefinition(
    key="car-register",
    title="CAR Register",
    module=MODULE,
    filename="CAR-Register",
    view_permissions=(Permission.CAR_VIEW,),
    export_permission=Permission.CAR_EXPORT,
    filters=CarRegisterFilters,
    formats=("xlsx",),
    build=build_register,
)
