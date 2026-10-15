"""Process Safety Management figures, computed from recommendation and action rows.

Pure functions: the Command Center, the register filters and the tests use the
same definitions, so a figure and the list it opens always agree.

Official figures leave out draft and archived recommendations. A count with
nothing to count is 0; a percentage with no denominator is None (shown as "—"),
never NaN.
"""

import datetime as dt
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.safety.psm.reference import AGING_BUCKETS, RISK_RANK

UNASSIGNED = "Unassigned"

# Lifecycle stages, in order. A recommendation counts in every stage it has
# reached, so each stage holds at most as many as the one before it.
STAGES: tuple[tuple[str, str, str], ...] = (
    ("identified", "Identified", "Every recommendation in scope."),
    ("reviewed", "Reviewed", "A disposition has been decided: accepted or rejected."),
    ("accepted", "Accepted", "Accepted; an action has been generated."),
    (
        "assigned",
        "Assigned",
        "Accepted, and the action has an owner and a due date.",
    ),
    (
        "in_progress",
        "In Progress",
        "Work has started: the action is In Progress, Pending Verification or Closed.",
    ),
    (
        "verification",
        "Verification",
        "Closure has been requested: the action is Pending Verification or Closed.",
    ),
    ("closed", "Closed", "Closure verified and the action closed."),
)
REJECTED_STAGE = ("rejected", "Rejected", "Rejected with a documented justification.")

MATRIX_COLUMNS: tuple[tuple[str, str], ...] = (
    ("no_action", "No Action / Pending Disposition"),
    ("not_started", "Not Started"),
    ("in_progress", "In Progress"),
    ("pending_verification", "Pending Verification"),
    ("closed", "Closed"),
)

DUE_STATES = ("overdue", "due_7", "due_30", "later", "no_due_date", "closed")


@dataclass(frozen=True)
class ActionView:
    id: int
    action_number: str
    status: str
    department_id: int | None
    department: str | None
    owner_key: str | None
    owner: str | None
    due_date: dt.date | None
    created_on: dt.date
    returned: bool = False
    failed_notification: bool = False
    requires_resolution: bool = False
    archived: bool = False

    @property
    def is_open(self) -> bool:
        return self.status != "closed" and not self.archived


@dataclass(frozen=True)
class RecommendationView:
    id: int
    study_id: int
    display_id: str
    disposition: str
    scenario_risks: tuple[str, ...]
    action: ActionView | None
    is_draft: bool = False
    archived: bool = False
    extra: dict[str, object] = field(default_factory=dict, compare=False)

    @property
    def official(self) -> bool:
        return not self.is_draft and not self.archived


def governing_risk(risks: Iterable[str]) -> str | None:
    """The highest scenario risk; None when there are no scenarios."""
    ranked = [r for r in risks if r in RISK_RANK]
    return max(ranked, key=RISK_RANK.__getitem__) if ranked else None


def is_overdue(action: ActionView | None, today: dt.date) -> bool:
    return (
        action is not None
        and action.is_open
        and action.due_date is not None
        and action.due_date < today
    )


def needs_scheduling(action: ActionView | None) -> bool:
    return action is not None and action.is_open and action.due_date is None


def due_state(action: ActionView | None, today: dt.date) -> str | None:
    """overdue, due_7 (today to 7 days), due_30 (8 to 30 days), later,
    no_due_date or closed; None without an action."""
    if action is None:
        return None
    if action.status == "closed":
        return "closed"
    if action.due_date is None:
        return "no_due_date"
    days = (action.due_date - today).days
    if days < 0:
        return "overdue"
    if days <= 7:
        return "due_7"
    if days <= 30:
        return "due_30"
    return "later"


def age_days(action: ActionView, today: dt.date) -> int:
    return max((today - action.created_on).days, 0)


def aging_bucket(action: ActionView, today: dt.date) -> str:
    days = age_days(action, today)
    for code, _, low, high in AGING_BUCKETS:
        if days >= low and (high is None or days <= high):
            return code
    return AGING_BUCKETS[-1][0]


def needs_attention(action: ActionView, today: dt.date) -> list[str]:
    """Why an open action needs attention (empty when it does not)."""
    if not action.is_open:
        return []
    reasons: list[str] = []
    if is_overdue(action, today):
        reasons.append("overdue")
    if action.owner_key is None:
        reasons.append("missing_owner")
    if action.department_id is None:
        reasons.append("missing_department")
    if action.due_date is None:
        reasons.append("missing_due_date")
    if action.returned:
        reasons.append("returned_or_reopened")
    if action.failed_notification:
        reasons.append("notification_failed")
    if action.requires_resolution:
        reasons.append("requires_resolution")
    return reasons


def stages(rec: RecommendationView) -> set[str]:
    """Every lifecycle stage the recommendation has reached."""
    reached = {"identified"}
    if rec.disposition == "rejected":
        return reached | {"reviewed", "rejected"}
    if rec.disposition != "accepted":
        return reached
    reached |= {"reviewed", "accepted"}
    action = rec.action
    if action is None:
        return reached
    if action.owner_key is not None and action.due_date is not None:
        reached.add("assigned")
    if action.status in ("in_progress", "pending_verification", "closed"):
        reached.add("in_progress")
    if action.status in ("pending_verification", "closed"):
        reached.add("verification")
    if action.status == "closed":
        reached.add("closed")
    return reached


def matrix_column(rec: RecommendationView) -> str | None:
    """The Risk x Action Status column; None for rejected recommendations."""
    if rec.disposition == "rejected":
        return None
    if rec.action is None or rec.disposition != "accepted":
        return "no_action"
    return rec.action.status


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


@dataclass(frozen=True)
class Kpis:
    total: int
    pending: int
    accepted: int
    rejected: int
    not_started: int
    in_progress: int
    pending_verification: int
    closed: int
    overdue: int
    needs_scheduling: int
    closure_pct: float | None
    actions: int


def kpis(recs: Sequence[RecommendationView], today: dt.date) -> Kpis:
    official = [r for r in recs if r.official]
    dispositions = Counter(r.disposition for r in official)
    actions = [
        r.action
        for r in official
        if r.disposition == "accepted" and r.action and not r.action.archived
    ]
    statuses = Counter(a.status for a in actions)
    return Kpis(
        total=len(official),
        pending=dispositions["pending_review"],
        accepted=dispositions["accepted"],
        rejected=dispositions["rejected"],
        not_started=statuses["not_started"],
        in_progress=statuses["in_progress"],
        pending_verification=statuses["pending_verification"],
        closed=statuses["closed"],
        overdue=sum(is_overdue(a, today) for a in actions),
        needs_scheduling=sum(needs_scheduling(a) for a in actions),
        closure_pct=_pct(statuses["closed"], len(actions)),
        actions=len(actions),
    )


def lifecycle(recs: Sequence[RecommendationView]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for rec in recs:
        if rec.official:
            counts.update(stages(rec))
    return {code: counts[code] for code, _, _ in (*STAGES, REJECTED_STAGE)}


def scenario_risks(recs: Sequence[RecommendationView]) -> dict[str, int]:
    counts = Counter(risk for r in recs if r.official for risk in r.scenario_risks)
    return {risk: counts[risk] for risk in RISK_RANK}


def governing_risks(recs: Sequence[RecommendationView]) -> dict[str, int]:
    counts = Counter(governing_risk(r.scenario_risks) for r in recs if r.official)
    return {risk: counts[risk] for risk in RISK_RANK}


def matrix(recs: Sequence[RecommendationView]) -> dict[str, dict[str, int]]:
    cells: dict[str, dict[str, int]] = {
        risk: {code: 0 for code, _ in MATRIX_COLUMNS} for risk in RISK_RANK
    }
    for rec in recs:
        if not rec.official:
            continue
        risk = governing_risk(rec.scenario_risks)
        column = matrix_column(rec)
        if risk is not None and column is not None:
            cells[risk][column] += 1
    return cells


def _active_actions(recs: Sequence[RecommendationView]) -> list[ActionView]:
    return [r.action for r in recs if r.official and r.action is not None and not r.action.archived]


def by_department(
    recs: Sequence[RecommendationView],
) -> list[tuple[str, int | None, dict[str, int]]]:
    """(department, department id, counts by status), largest first; Unassigned last."""
    groups: dict[tuple[str, int | None], Counter[str]] = {}
    for action in _active_actions(recs):
        key = (action.department or UNASSIGNED, action.department_id)
        groups.setdefault(key, Counter())[action.status] += 1
    named = sorted(
        (k for k in groups if k[1] is not None), key=lambda k: (-sum(groups[k].values()), k[0])
    )
    ordered = named + [k for k in groups if k[1] is None]
    return [
        (
            name,
            dep_id,
            {
                s: groups[(name, dep_id)][s]
                for s in ("not_started", "in_progress", "pending_verification", "closed")
            },
        )
        for name, dep_id in ordered
    ]


def aging(recs: Sequence[RecommendationView], today: dt.date) -> dict[str, int]:
    """Open actions by days since the action was created."""
    counts = Counter(aging_bucket(a, today) for a in _active_actions(recs) if a.is_open)
    return {code: counts[code] for code, _, _, _ in AGING_BUCKETS}


def deadlines(
    recs: Sequence[RecommendationView], today: dt.date, days: int
) -> list[RecommendationView]:
    """Open actions due from today through ``days`` ahead, soonest first."""
    end = today + dt.timedelta(days=days)
    found = [
        r
        for r in recs
        if r.official
        and r.action is not None
        and r.action.is_open
        and r.action.due_date is not None
        and today <= r.action.due_date <= end
    ]
    return sorted(found, key=lambda r: (r.action.due_date, r.display_id))  # type: ignore[union-attr]


def overdue(recs: Sequence[RecommendationView], today: dt.date) -> list[RecommendationView]:
    found = [r for r in recs if r.official and is_overdue(r.action, today)]
    return sorted(found, key=lambda r: (r.action.due_date, r.display_id))  # type: ignore[union-attr]


@dataclass(frozen=True)
class OwnerLoad:
    owner: str
    owner_key: str | None
    not_started: int
    in_progress: int
    pending_verification: int
    overdue: int

    @property
    def total_active(self) -> int:
        return self.not_started + self.in_progress + self.pending_verification


def distribution(recs: Sequence[RecommendationView], today: dt.date) -> list[OwnerLoad]:
    """Open actions per owner (platform users, external owners, Unassigned)."""
    groups: dict[str | None, list[ActionView]] = {}
    labels: dict[str | None, str] = {None: UNASSIGNED}
    for action in _active_actions(recs):
        if not action.is_open:
            continue
        groups.setdefault(action.owner_key, []).append(action)
        if action.owner_key is not None:
            labels[action.owner_key] = action.owner or UNASSIGNED
    loads = [
        OwnerLoad(
            owner=labels[key],
            owner_key=key,
            not_started=sum(a.status == "not_started" for a in actions),
            in_progress=sum(a.status == "in_progress" for a in actions),
            pending_verification=sum(a.status == "pending_verification" for a in actions),
            overdue=sum(is_overdue(a, today) for a in actions),
        )
        for key, actions in groups.items()
    ]
    return sorted(loads, key=lambda load: (load.owner_key is None, load.owner.lower()))
