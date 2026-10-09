"""My Assignments: open work assigned to the signed-in user, across modules.

The user is always the session user; the request names nobody. Only items in
modules the user may view are listed:

- CARs assigned to the user that are not closed (``car.view``)
- CAR actions owned by the user that are not complete (``car.view``)
- Quality Cost records owned by the user that are not closed (``qualityCost.view``)
"""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.authorization import UserPrincipal, require_permission
from app.core.permissions import Permission
from app.core.schemas import CamelModel
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.quality.car.models import Car, CarAction
from app.quality.cost.models import CostRecord
from app.quality.cost.records import record_number
from app.safety.site_calendar import site_today

router = APIRouter(prefix="/assignments", tags=["assignments"])

AssignmentKind = Literal["car", "car_action", "quality_cost"]


class AssignmentOut(CamelModel):
    kind: AssignmentKind
    id: int
    # The CAR an action belongs to; None for other kinds.
    car_id: int | None
    reference: str
    title: str
    status: str | None
    due_date: dt.date | None
    overdue: bool


class AssignmentsResponse(CamelModel):
    assignments: list[AssignmentOut]


def _database_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "database_unavailable",
            "message": "Assignments are unavailable because the database could not be reached.",
        },
    )


def assignments_session() -> Iterator[Session]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield session


SessionDep = Annotated[Session, Depends(assignments_session)]
Assignee = Annotated[UserPrincipal, Depends(require_permission(Permission.ASSIGNMENTS_VIEW_OWN))]


def _overdue(due: dt.date | None, today: dt.date) -> bool:
    return due is not None and due < today


@router.get("/mine", response_model=AssignmentsResponse)
def my_assignments(principal: Assignee, db: SessionDep) -> AssignmentsResponse:
    """Open items assigned to you, earliest due date first (undated last)."""
    user_id = principal.user_id
    today = site_today(dt.datetime.now(dt.UTC))
    items: list[AssignmentOut] = []
    try:
        if principal.has(Permission.CAR_VIEW):
            cars = db.scalars(
                select(Car).where(
                    Car.assigned_to_user_id == user_id, Car.status.is_distinct_from("closed")
                )
            )
            items.extend(
                AssignmentOut(
                    kind="car",
                    id=car.id,
                    car_id=car.id,
                    reference=car.car_number,
                    title=car.subject,
                    status=car.status,
                    due_date=car.due_date,
                    overdue=_overdue(car.due_date, today),
                )
                for car in cars
            )
            actions = db.execute(
                select(CarAction, Car.car_number)
                .join(Car, Car.id == CarAction.car_id)
                .where(
                    CarAction.owner_user_id == user_id,
                    CarAction.status.is_distinct_from("complete"),
                    Car.status.is_distinct_from("closed"),
                )
            )
            items.extend(
                AssignmentOut(
                    kind="car_action",
                    id=action.id,
                    car_id=action.car_id,
                    reference=f"{car_number} action {action.position}",
                    title=action.action,
                    status=action.status,
                    due_date=action.target_date,
                    overdue=_overdue(action.target_date, today),
                )
                for action, car_number in actions
            )
        if principal.has(Permission.QUALITY_COST_VIEW):
            records = db.scalars(
                select(CostRecord).where(
                    CostRecord.owner_user_id == user_id, CostRecord.status != "closed"
                )
            )
            items.extend(
                AssignmentOut(
                    kind="quality_cost",
                    id=record.id,
                    car_id=None,
                    reference=record_number(record.id),
                    title=record.title,
                    status=record.status,
                    due_date=record.due_date,
                    overdue=_overdue(record.due_date, today),
                )
                for record in records
            )
    except SQLAlchemyError:
        raise _database_unavailable() from None
    items.sort(key=lambda i: (i.due_date is None, i.due_date or today, i.reference))
    return AssignmentsResponse(assignments=items)
