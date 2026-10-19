"""Load template context from domain records (administration test center)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.safety.psm.models import PsmAction, PsmRecommendation
from app.safety.psm.notifications import recipient as psm_recipient
from app.safety.psm.reference import ACTION_STATUSES


def get_psm_action_context(
    session: Session, action_id: int, *, settings: Settings
) -> dict[str, object]:
    """Flat dotted keys suitable for ``build_context`` / template rendering."""
    row = session.execute(
        select(PsmAction, PsmRecommendation)
        .join(PsmRecommendation, PsmRecommendation.id == PsmAction.recommendation_id)
        .where(PsmAction.id == action_id)
    ).one_or_none()
    if row is None:
        raise LookupError("psm_action_not_found")
    action, recommendation = row
    owner_name, owner_email = psm_recipient(session, action)
    base = settings.app_public_url.rstrip("/") if settings.app_public_url else ""
    action_url = f"{base}/safety/psm/actions/{action.id}" if base else ""
    due = action.due_date.isoformat() if action.due_date is not None else ""
    status_label = ACTION_STATUSES.get(action.status, action.status)
    return {
        "owner_name": owner_name,
        "owner_email": owner_email,
        "action.reference": action.action_number,
        "action.title": action.title,
        "action.owner_name": owner_name or "",
        "action.due_date": due,
        "action.status": status_label,
        "action.url": action_url,
        "recommendation.reference": recommendation.display_id,
        "entity.reference": action.action_number,
        "entity.url": action_url,
    }


def list_psm_actions_for_test(session: Session, *, limit: int = 50) -> list[dict[str, object]]:
    rows = session.execute(
        select(PsmAction.id, PsmAction.action_number, PsmAction.title, PsmAction.owner_name)
        .where(PsmAction.archived_at.is_(None))
        .order_by(PsmAction.updated_at.desc())
        .limit(min(limit, 200))
    ).all()
    return [
        {
            "id": action_id,
            "reference": reference,
            "title": title,
            "owner_name": owner_name,
        }
        for action_id, reference, title, owner_name in rows
    ]
