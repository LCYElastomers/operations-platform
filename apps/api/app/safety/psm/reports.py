"""Process Safety Management exports: the recommendation register (with a
separate, normalized Scenarios sheet - one row per scenario, never concatenated)
and the action register. Both apply the same filters as the screens."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.permissions import Permission
from app.reports.definitions import ReportContent, ReportContext, ReportDefinition
from app.reports.model import Column, Table, Value
from app.safety.psm import service
from app.safety.psm.models import PsmAction, PsmRecommendation, PsmScenario
from app.safety.psm.reference import ACTION_STATUSES, DISPOSITIONS, RISKS
from app.safety.psm.store import PsmStore

MODULE = "Process Safety Management"
Code = Annotated[str, Field(min_length=1, max_length=100)]
Codes = Annotated[list[Code], Field(default_factory=list, max_length=30)]


class _Filters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    study_id: int | None = Field(default=None, alias="studyId")
    search: Annotated[str, Field(max_length=200)] | None = Field(default=None, alias="q")
    department: Codes
    owner: Codes


class RecommendationFilters(_Filters):
    disposition: Codes
    action_status: Codes = Field(default_factory=list, alias="actionStatus")
    governing_risk: Codes = Field(default_factory=list, alias="governingRisk")
    scenario_risk: Codes = Field(default_factory=list, alias="scenarioRisk")
    equipment: Codes
    node: Annotated[list[int], Field(default_factory=list, max_length=30)]
    due_state: Codes = Field(default_factory=list, alias="dueState")
    overdue: bool = False
    unassigned: bool = False
    missing_due_date: bool = Field(default=False, alias="missingDueDate")
    stage: Code | None = None
    matrix_risk: Code | None = Field(default=None, alias="matrixRisk")
    matrix_column: Code | None = Field(default=None, alias="matrixColumn")
    drafts: bool = False
    archived: bool = False
    sort: Code = "id"
    desc: bool = False


class ActionFilters(_Filters):
    tab: Literal[
        "all",
        "attention",
        "not_started",
        "in_progress",
        "pending_verification",
        "overdue",
        "closed",
    ] = "all"
    risk: Codes
    due_state: Codes = Field(default_factory=list, alias="dueState")
    aging: Literal["0_30", "31_60", "61_90", "90_plus"] | None = None
    archived: bool = False
    sort: Code = "dueDate"
    desc: bool = False


def register_filter(f: RecommendationFilters) -> service.RegisterFilter:
    return service.RegisterFilter(
        study_id=f.study_id,
        dispositions=tuple(f.disposition),
        action_statuses=tuple(f.action_status),
        governing_risks=tuple(f.governing_risk),
        scenario_risks=tuple(f.scenario_risk),
        departments=tuple(f.department),
        owners=tuple(f.owner),
        equipment=tuple(f.equipment),
        nodes=tuple(f.node),
        due_states=tuple(f.due_state),
        overdue=f.overdue,
        unassigned=f.unassigned,
        missing_due_date=f.missing_due_date,
        stage=f.stage,
        matrix_risk=f.matrix_risk,
        matrix_column=f.matrix_column,
        search=f.search,
        include_drafts=f.drafts,
        include_archived=f.archived,
    )


def action_filter(f: ActionFilters) -> service.ActionFilter:
    return service.ActionFilter(
        tab=f.tab,
        study_id=f.study_id,
        departments=tuple(f.department),
        owners=tuple(f.owner),
        risks=tuple(f.risk),
        due_states=tuple(f.due_state),
        aging=f.aging,
        search=f.search,
        include_archived=f.archived,
    )


def _applied(f: _Filters, extra: list[tuple[str, str]]) -> list[tuple[str, str]]:
    applied = []
    if f.study_id is not None:
        applied.append(("Study ID", str(f.study_id)))
    if f.search:
        applied.append(("Search", f.search))
    if f.department:
        applied.append(("Department", ", ".join(f.department)))
    if f.owner:
        applied.append(("Owner", ", ".join(f.owner)))
    return applied + extra


def _label(code: str | None, labels: dict[str, str]) -> str | None:
    return labels.get(code, code) if code else None


RECOMMENDATION_COLUMNS = [
    Column("Study", "text", 24),
    Column("Recommendation ID", "text", 16),
    Column("Recommendation Number", "int", 10),
    Column("Area/Equipment", "text", 16),
    Column("Recommendation", "text", 60),
    Column("Process Node", "text", 36),
    Column("Governing Risk", "text", 10),
    Column("Scenario Count", "int", 9),
    Column("Disposition", "text", 14),
    Column("Disposition Justification", "text", 40),
    Column("Department", "text", 20),
    Column("Owner", "text", 20),
    Column("Owner Email", "text", 26),
    Column("Due Date", "date", 12),
    Column("Action Status", "text", 16),
    Column("Task", "text", 40),
    Column("Notes", "text", 30),
]
SCENARIO_COLUMNS = [
    Column("Recommendation ID", "text", 16),
    Column("Scenario Sequence", "int", 9),
    Column("Event", "text", 40),
    Column("Cause", "text", 40),
    Column("Consequence", "text", 50),
    Column("Risk", "text", 10),
    Column("Area/Equipment", "text", 16),
    Column("Process Node", "text", 36),
]


def build_recommendations(ctx: ReportContext) -> ReportContent:
    f = ctx.filters
    assert isinstance(f, RecommendationFilters)  # noqa: S101 - set by the definition
    store = PsmStore(ctx.session)
    criteria = register_filter(f)
    rows = service.register(store, criteria, ctx.today, sort=f.sort, descending=f.desc)
    scope = store.scope(
        recommendation_ids=[r.id for r in rows], include_archived=criteria.include_archived
    )
    recs: dict[int, PsmRecommendation] = {r.id: r for r in scope.recommendations}
    studies = scope.studies
    register_rows: list[list[Value]] = []
    scenario_rows: list[list[Value]] = []
    for row in rows:
        rec = recs[row.id]
        action: PsmAction | None = scope.actions.get(rec.id)
        register_rows.append(
            [
                studies[rec.study_id].title,
                row.display_id,
                row.recommendation_number,
                row.area_equipment,
                row.recommendation_text,
                row.process_node,
                _label(row.governing_risk, RISKS),
                row.scenario_count,
                DISPOSITIONS[row.disposition] + (" (draft)" if row.is_draft else ""),
                rec.disposition_justification,
                row.department,
                row.owner,
                action.owner_email if action else None,
                row.due_date,
                _label(row.action_status, ACTION_STATUSES),
                action.description if action else None,
                rec.notes,
            ]
        )
        scenarios: list[PsmScenario] = scope.scenarios.get(rec.id, [])
        for scenario in scenarios:
            node = scope.nodes.get(scenario.process_node_id) if scenario.process_node_id else None
            scenario_rows.append(
                [
                    row.display_id,
                    scenario.sequence_number,
                    scenario.event,
                    scenario.cause,
                    scenario.consequence,
                    RISKS[scenario.risk],
                    scenario.area_equipment,
                    node.name if node else None,
                ]
            )
    applied = _applied(
        f,
        [
            *([("Disposition", ", ".join(f.disposition))] if f.disposition else []),
            *([("Action status", ", ".join(f.action_status))] if f.action_status else []),
            *([("Governing risk", ", ".join(f.governing_risk))] if f.governing_risk else []),
            *([("Scenario risk", ", ".join(f.scenario_risk))] if f.scenario_risk else []),
            *([("Overdue", "Yes")] if f.overdue else []),
            *([("Unassigned", "Yes")] if f.unassigned else []),
            *([("Missing due date", "Yes")] if f.missing_due_date else []),
            *([("Lifecycle stage", f.stage)] if f.stage else []),
            *([("Drafts", "Included")] if f.drafts else []),
            *([("Archived", "Included")] if f.archived else []),
        ],
    )
    return ReportContent(
        filters=applied,
        tables=[
            Table(
                "Recommendations",
                RECOMMENDATION_COLUMNS,
                register_rows,
                sheet="Recommendations",
                description="One row per recommendation. Department, owner, due date, status and "
                "task are those of the linked action.",
            ),
            Table(
                "Hazard Scenarios",
                SCENARIO_COLUMNS,
                scenario_rows,
                sheet="Scenarios",
                description="One row per hazard scenario, linked by Recommendation ID.",
            ),
        ],
        notes=[
            "Governing risk is the highest risk among a recommendation's hazard scenarios.",
            "Blank cells are values not recorded; they are not zero.",
        ],
    )


ACTION_COLUMNS = [
    Column("Action ID", "text", 18),
    Column("Recommendation ID", "text", 16),
    Column("Study", "text", 24),
    Column("Equipment", "text", 16),
    Column("Node", "text", 36),
    Column("Risk", "text", 10),
    Column("Action", "text", 50),
    Column("Department", "text", 20),
    Column("Owner", "text", 20),
    Column("Owner Email", "text", 26),
    Column("Due Date", "date", 12),
    Column("Status", "text", 18),
    Column("Age (days)", "int", 9),
    Column("Closure Summary", "text", 40),
    Column("Closed Date", "date", 12),
]


def build_actions(ctx: ReportContext) -> ReportContent:
    f = ctx.filters
    assert isinstance(f, ActionFilters)  # noqa: S101 - set by the definition
    store = PsmStore(ctx.session)
    rows, _ = service.action_list(
        store, action_filter(f), ctx.today, sort=f.sort, descending=f.desc
    )
    scope = store.scope(
        recommendation_ids=[a.recommendation_id for a in rows], include_archived=True
    )
    recs = {r.id: r for r in scope.recommendations}
    table_rows: list[list[Value]] = []
    for a in rows:
        rec = recs[a.recommendation_id]
        node = scope.nodes.get(rec.process_node_id) if rec.process_node_id else None
        closed: dt.date | None = a.closed_at.date() if a.closed_at else None
        table_rows.append(
            [
                a.action_number,
                a.recommendation_display_id,
                scope.studies[rec.study_id].title,
                a.area_equipment,
                node.name if node else None,
                _label(a.governing_risk, RISKS),
                a.description or a.title,
                a.department,
                a.owner_name,
                a.owner_email,
                a.due_date,
                ACTION_STATUSES[a.status],
                a.age_days,
                a.closure_summary,
                closed,
            ]
        )
    return ReportContent(
        filters=_applied(
            f,
            [
                ("View", f.tab.replace("_", " ").title()),
                *([("Risk", ", ".join(f.risk))] if f.risk else []),
            ],
        ),
        tables=[Table("Action Items", ACTION_COLUMNS, table_rows, sheet="Actions")],
        notes=[
            "Age is days since the action was created. "
            "Risk is the recommendation's governing risk.",
        ],
    )


RECOMMENDATIONS = ReportDefinition(
    key="psm-recommendations",
    title="PSM Recommendation Register",
    module=MODULE,
    filename="PSM-Recommendations",
    view_permissions=(Permission.PSM_VIEW,),
    export_permission=Permission.PSM_EXPORT,
    filters=RecommendationFilters,
    formats=("xlsx",),
    period_modes=frozenset({"all"}),
    build=build_recommendations,
)

ACTIONS = ReportDefinition(
    key="psm-actions",
    title="PSM Action Register",
    module=MODULE,
    filename="PSM-Actions",
    view_permissions=(Permission.PSM_VIEW,),
    export_permission=Permission.PSM_EXPORT,
    filters=ActionFilters,
    formats=("xlsx",),
    period_modes=frozenset({"all"}),
    build=build_actions,
)
