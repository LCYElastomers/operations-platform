"""Database access for the monthly Cost of Quality inputs."""

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.quality.cost.models import CostMonthlyFact


class CostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def facts(self) -> dict[tuple[int, int], CostMonthlyFact]:
        rows = self.session.scalars(
            select(CostMonthlyFact).order_by(
                CostMonthlyFact.reporting_year, CostMonthlyFact.reporting_month
            )
        )
        return {(row.reporting_year, row.reporting_month): row for row in rows}

    def lock(self) -> None:
        """Serialize imports until the transaction ends."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "quality.cost_monthly_facts"},
        )

    def insert(
        self, year: int, month: int, values: dict[str, Any], *, actor_id: str, at: dt.datetime
    ) -> None:
        self.session.execute(
            insert(CostMonthlyFact).values(
                reporting_year=year,
                reporting_month=month,
                **values,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
        )

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
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

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
