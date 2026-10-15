"""Database access for Process Safety Management.

Lists and figures load a scope in a fixed number of queries (recommendations,
then their scenarios, actions and reference names in bulk), never one query per
row. Writes happen in the caller's transaction; ``commit`` ends it.
"""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.recorder import AuditChange, record_changes
from app.auth import people
from app.auth.models import User
from app.safety.models import Area
from app.safety.psm.models import (
    PsmAction,
    PsmActionUpdate,
    PsmAttachment,
    PsmDepartment,
    PsmElement,
    PsmNotification,
    PsmProcessNode,
    PsmRecommendation,
    PsmScenario,
    PsmStudy,
    PsmStudyArea,
    PsmStudyType,
)

NUMBER_LOCK_KEY = "safety.psm.numbers"
IMPORT_LOCK_KEY = "safety.psm.import"
ENTITY_TYPES = (
    "safety.psm_study",
    "safety.psm_recommendation",
    "safety.psm_scenario",
    "safety.psm_action",
    "safety.psm_attachment",
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class Scope:
    """Recommendations in scope with everything their rows and figures need."""

    recommendations: list[PsmRecommendation]
    scenarios: dict[int, list[PsmScenario]]
    actions: dict[int, PsmAction]
    studies: dict[int, PsmStudy]
    nodes: dict[int, PsmProcessNode]
    departments: dict[int, PsmDepartment]
    failed_notifications: set[int] = field(default_factory=set)


class PsmStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    # Transactions ----------------------------------------------------------------

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def flush(self) -> None:
        self.session.flush()

    def lock(self, key: str) -> None:
        """Serialize writers of ``key`` until the transaction ends."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )

    def audit(
        self,
        *,
        actor_id: str,
        change_set_id: Any,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None:
        record_changes(
            self.session,
            actor_id=actor_id,
            change_set_id=change_set_id,
            occurred_at=at,
            changes=changes,
        )

    def actor_names(self, actor_ids: Iterable[str | None]) -> dict[str, str]:
        return people.display_names(self.session, actor_ids)

    # Single records ----------------------------------------------------------------

    def get(self, model: Any, row_id: Any, *, for_update: bool = False) -> Any:
        statement = select(model).where(model.__mapper__.primary_key[0] == row_id)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(statement)

    def user(self, user_id: Any) -> User | None:
        return self.session.get(User, user_id)

    def action_of(self, recommendation_id: int, *, for_update: bool = False) -> PsmAction | None:
        statement = select(PsmAction).where(PsmAction.recommendation_id == recommendation_id)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(statement)

    def scenarios_of(self, recommendation_id: int) -> list[PsmScenario]:
        return list(
            self.session.scalars(
                select(PsmScenario)
                .where(PsmScenario.recommendation_id == recommendation_id)
                .order_by(PsmScenario.sequence_number, PsmScenario.id)
            )
        )

    def attachments(
        self, *, recommendation_id: int | None = None, action_id: int | None = None
    ) -> list[PsmAttachment]:
        a = PsmAttachment
        conditions = []
        if recommendation_id is not None:
            conditions.append(a.recommendation_id == recommendation_id)
        if action_id is not None:
            conditions.append(a.action_id == action_id)
        if not conditions:
            return []
        return list(
            self.session.scalars(select(a).where(or_(*conditions)).order_by(a.uploaded_at, a.id))
        )

    def active_evidence_count(self, action_id: int) -> int:
        a = PsmAttachment
        return (
            self.session.scalar(
                select(func.count()).where(a.action_id == action_id, a.removed_at.is_(None))
            )
            or 0
        )

    def updates(self, action_id: int) -> list[PsmActionUpdate]:
        u = PsmActionUpdate
        return list(
            self.session.scalars(
                select(u).where(u.action_id == action_id).order_by(u.created_at, u.id)
            )
        )

    def notifications(self, action_id: int) -> list[PsmNotification]:
        n = PsmNotification
        return list(
            self.session.scalars(
                select(n).where(n.action_id == action_id).order_by(n.created_at.desc(), n.id.desc())
            )
        )

    # Numbers -------------------------------------------------------------------------

    def next_recommendation_number(self, study_id: int) -> int:
        r = PsmRecommendation
        current = self.session.scalar(
            select(func.max(r.recommendation_number)).where(r.study_id == study_id)
        )
        return (current or 0) + 1

    def next_action_sequence(self, year: int) -> int:
        prefix = f"PSM-ACT-{year}-"
        numbers = self.session.scalars(
            select(PsmAction.action_number).where(PsmAction.action_number.like(f"{prefix}%"))
        )
        return max((int(n.removeprefix(prefix)) for n in numbers), default=0) + 1

    def next_scenario_number(self, recommendation_id: int) -> int:
        s = PsmScenario
        current = self.session.scalar(
            select(func.max(s.sequence_number)).where(s.recommendation_id == recommendation_id)
        )
        return (current or 0) + 1

    # Reference -----------------------------------------------------------------------

    def study_types(self) -> list[PsmStudyType]:
        t = PsmStudyType
        return list(self.session.scalars(select(t).order_by(t.display_order, t.id)))

    def departments(self) -> list[PsmDepartment]:
        d = PsmDepartment
        return list(self.session.scalars(select(d).order_by(d.display_order, func.lower(d.name))))

    def process_nodes(self) -> list[PsmProcessNode]:
        n = PsmProcessNode
        return list(self.session.scalars(select(n).order_by(n.display_order, n.id)))

    def elements(self) -> list[PsmElement]:
        e = PsmElement
        return list(self.session.scalars(select(e).order_by(e.display_order)))

    def areas(self) -> list[Area]:
        return list(self.session.scalars(select(Area).order_by(Area.code)))

    def studies(self) -> list[PsmStudy]:
        s = PsmStudy
        return list(self.session.scalars(select(s).order_by(s.year.desc(), s.study_code)))

    def study_areas(self, study_ids: Sequence[int]) -> dict[int, list[Area]]:
        if not study_ids:
            return {}
        rows = self.session.execute(
            select(PsmStudyArea.study_id, Area)
            .join(Area, Area.id == PsmStudyArea.area_id)
            .where(PsmStudyArea.study_id.in_(study_ids))
            .order_by(Area.code)
        ).all()
        found: dict[int, list[Area]] = {}
        for study_id, area in rows:
            found.setdefault(study_id, []).append(area)
        return found

    def set_study_areas(self, study_id: int, area_ids: Sequence[int]) -> None:
        current = {
            row
            for row in self.session.scalars(
                select(PsmStudyArea.area_id).where(PsmStudyArea.study_id == study_id)
            )
        }
        wanted = set(area_ids)
        for area_id in current - wanted:
            self.session.delete(self.session.get(PsmStudyArea, (study_id, area_id)))
        for area_id in sorted(wanted - current):
            self.session.add(PsmStudyArea(study_id=study_id, area_id=area_id))

    def name_key_taken(self, model: Any, name_key: str, except_id: int | None = None) -> bool:
        statement = select(model.id).where(model.name_key == name_key)
        if except_id is not None:
            statement = statement.where(model.id != except_id)
        return self.session.scalar(statement) is not None

    # Scope ---------------------------------------------------------------------------

    def scope(
        self,
        *,
        study_id: int | None = None,
        recommendation_ids: Sequence[int] | None = None,
        include_archived: bool = False,
    ) -> Scope:
        r = PsmRecommendation
        statement = select(r)
        if study_id is not None:
            statement = statement.where(r.study_id == study_id)
        if recommendation_ids is not None:
            statement = statement.where(r.id.in_(recommendation_ids))
        if not include_archived:
            statement = statement.where(r.archived_at.is_(None))
        recommendations = list(
            self.session.scalars(statement.order_by(r.study_id, r.recommendation_number))
        )
        ids = [rec.id for rec in recommendations]
        scenarios: dict[int, list[PsmScenario]] = {}
        actions: dict[int, PsmAction] = {}
        failed: set[int] = set()
        if ids:
            for scenario in self.session.scalars(
                select(PsmScenario)
                .where(PsmScenario.recommendation_id.in_(ids))
                .order_by(PsmScenario.recommendation_id, PsmScenario.sequence_number)
            ):
                scenarios.setdefault(scenario.recommendation_id, []).append(scenario)
            for action in self.session.scalars(
                select(PsmAction).where(PsmAction.recommendation_id.in_(ids))
            ):
                actions[action.recommendation_id] = action
            failed = self.failed_notification_actions([a.id for a in actions.values()])
        study_ids = sorted(
            {rec.study_id for rec in recommendations} | ({study_id} if study_id else set())
        )
        studies = (
            {
                s.id: s
                for s in self.session.scalars(select(PsmStudy).where(PsmStudy.id.in_(study_ids)))
            }
            if study_ids
            else {}
        )
        return Scope(
            recommendations=recommendations,
            scenarios=scenarios,
            actions=actions,
            studies=studies,
            nodes={n.id: n for n in self.process_nodes()},
            departments={d.id: d for d in self.departments()},
            failed_notifications=failed,
        )

    def failed_notification_actions(self, action_ids: Sequence[int]) -> set[int]:
        """Actions whose most recent notification failed."""
        if not action_ids:
            return set()
        n = PsmNotification
        latest = (
            select(n.action_id, func.max(n.id).label("last_id"))
            .where(n.action_id.in_(action_ids), n.status.in_(("sent", "failed")))
            .group_by(n.action_id)
            .subquery()
        )
        return set(
            self.session.scalars(
                select(n.action_id)
                .join(latest, latest.c.last_id == n.id)
                .where(n.status == "failed")
            )
        )

    def history(self, key: str) -> list[AuditEvent]:
        """Audit events of a record and everything under its key, oldest first."""
        a = AuditEvent
        return list(
            self.session.scalars(
                select(a)
                .where(
                    a.entity_type.in_(ENTITY_TYPES),
                    or_(
                        a.entity_key == key,
                        a.entity_key.like(f"{_escape_like(key)}/%", escape="\\"),
                    ),
                )
                .order_by(a.occurred_at, a.id)
            )
        )
