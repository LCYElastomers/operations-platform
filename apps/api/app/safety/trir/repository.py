"""Database access for TRIR Experience historical facts."""

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import insert, select, text, update
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.safety.trir.models import TrirAnnualFact


class TrirRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def facts(self) -> dict[int, TrirAnnualFact]:
        rows = self.session.scalars(select(TrirAnnualFact).order_by(TrirAnnualFact.reporting_year))
        return {row.reporting_year: row for row in rows}

    def lock(self) -> None:
        """Serialize imports until the transaction ends."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "safety.trir_annual_facts"},
        )

    def insert(self, year: int, values: dict[str, Any], *, actor_id: str, at: dt.datetime) -> None:
        self.session.execute(
            insert(TrirAnnualFact).values(
                reporting_year=year,
                **values,
                created_at=at,
                created_by=actor_id,
                updated_at=at,
                updated_by=actor_id,
            )
        )

    def update(self, year: int, values: dict[str, Any], *, actor_id: str, at: dt.datetime) -> None:
        self.session.execute(
            update(TrirAnnualFact)
            .where(TrirAnnualFact.reporting_year == year)
            .values(**values, updated_at=at, updated_by=actor_id)
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
