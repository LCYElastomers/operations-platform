"""Corrective Action Report rules, calculations, dashboard and import mapping.

Reports here are test fixtures built in memory. The import tests read the
reviewed mapping import_templates/quality_cars_2026.mapping.json, generated
from the workbooks in docs/cars.
"""

import datetime as dt
import itertools
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from principals import TESTER, TESTER_ID, TESTER_NAME
from pydantic import ValidationError

from app.core.permissions import Permission, module_of
from app.quality.car import calculations, dashboard, legacy_import, service, workbook
from app.quality.car.models import Car, CarAction
from app.quality.car.repository import CarRow
from app.quality.car.schemas import ActionFields, CarCreate, CarUpdate
from app.quality.cost.records import Actor, RecordForbiddenError, RecordRuleError

OTHER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")

TODAY = dt.date(2026, 10, 9)
NOW = dt.datetime(2026, 10, 9, 15, 0, tzinfo=dt.UTC)
API_ROOT = Path(__file__).resolve().parents[1]
MAPPING = API_ROOT / "import_templates" / "quality_cars_2026.mapping.json"
_ids = itertools.count(1)


def car(**overrides: Any) -> Car:
    """A fixture report: open, requested 1 September 2026, due 1 October 2026."""
    values: dict[str, Any] = {
        "id": next(_ids),
        "car_number": "Q-2026-900",
        "subject": "Fixture: label mismatch",
        "request_date": dt.date(2026, 9, 1),
        "due_date": dt.date(2026, 10, 1),
        "status": "open",
        "date_closed": None,
        "disposition_codes": [],
        "material_loss": None,
        "production_time_loss": None,
        "other_costs": None,
        "effectiveness_result": None,
        "previous_occurrence": None,
        "source": "manual",
        "version": 1,
        "created_at": NOW,
        "created_by": "fixture",
        "updated_at": NOW,
        "updated_by": "fixture",
        **overrides,
    }
    for column in Car.__table__.columns:
        values.setdefault(column.name, None)
    return Car(**values)


def action(**overrides: Any) -> CarAction:
    values: dict[str, Any] = {
        "id": next(_ids),
        "car_id": 1,
        "position": 1,
        "action": "Fixture action",
        "status": "open",
        "target_date": None,
        "completed_on": None,
        "version": 1,
        "created_at": NOW,
        "created_by": "fixture",
        "updated_at": NOW,
        "updated_by": "fixture",
        **overrides,
    }
    return CarAction(**values)


# Numbering -------------------------------------------------------------------------


def test_next_number_follows_the_highest_of_the_year_and_leaves_gaps() -> None:
    used = ["Q-2026-001", "Q-2026-002", "Q-2026-003", "Q-2026-005", "Q-2026-006", "Q-2025-040"]
    assert service.next_number(used, 2026) == "Q-2026-007"
    assert service.next_number(used, 2027) == "Q-2027-001"
    assert service.next_number([], 2026) == "Q-2026-001"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Q-2026-006", ("Q", 2026, 6)),
        (" Q-2026-1000 ", ("Q", 2026, 1000)),
        ("Q-2026-6", None),
        ("Q 2026 006", None),
        ("LCY-2026-037", ("LCY", 2026, 37)),
    ],
)
def test_parse_number(text: str, expected: Any) -> None:
    assert service.parse_number(text) == expected


def test_import_report_lists_numbers_without_a_workbook() -> None:
    numbers = ["Q-2026-001", "Q-2026-002", "Q-2026-003", "Q-2026-005", "Q-2026-006"]
    assert legacy_import.number_gaps(numbers) == ["Q-2026-004"]


# Calculations ----------------------------------------------------------------------


def test_days_open_counts_to_today_or_to_the_date_closed() -> None:
    assert calculations.days_open(car(), TODAY) == 38
    closed = car(status="closed", date_closed=dt.date(2026, 9, 11))
    assert calculations.days_open(closed, TODAY) == 10


def test_past_due_is_derived_from_status_and_due_date() -> None:
    assert calculations.is_past_due(car(), TODAY)
    assert not calculations.is_past_due(car(due_date=TODAY), TODAY)
    assert not calculations.is_past_due(car(due_date=None), TODAY)
    closed = car(status="closed", date_closed=dt.date(2026, 10, 2))
    assert not calculations.is_past_due(closed, TODAY)
    # An imported report without a recorded status is not closed.
    assert calculations.is_past_due(car(status=None, source="legacy_import"), TODAY)


def test_due_soon_includes_today_and_the_configured_window() -> None:
    assert calculations.is_due_soon(car(due_date=TODAY), TODAY, 14)
    assert calculations.is_due_soon(car(due_date=TODAY + dt.timedelta(days=14)), TODAY, 14)
    assert not calculations.is_due_soon(car(due_date=TODAY + dt.timedelta(days=15)), TODAY, 14)
    assert not calculations.is_due_soon(car(due_date=TODAY - dt.timedelta(days=1)), TODAY, 14)


def test_cost_total_is_null_when_nothing_is_entered_and_zero_when_zero_is() -> None:
    assert calculations.cost_total(car()) is None
    zeros = car(material_loss=Decimal(0), production_time_loss=Decimal(0))
    assert calculations.cost_total(zeros) == Decimal(0)
    entered = car(material_loss=Decimal("120.50"), other_costs=Decimal("30"))
    assert calculations.cost_total(entered) == Decimal("150.50")


def test_action_progress_and_awaiting_effectiveness() -> None:
    actions = [
        action(status="complete", completed_on=dt.date(2026, 9, 20)),
        action(status="in_progress", target_date=dt.date(2026, 9, 30)),
        action(status=None),
    ]
    progress = calculations.action_progress(actions, TODAY)
    assert (progress.total, progress.complete, progress.outstanding, progress.overdue) == (
        3,
        1,
        2,
        1,
    )
    assert not progress.all_complete
    assert not calculations.awaiting_effectiveness(car(), progress)

    done = calculations.action_progress([action(status="complete")], TODAY)
    assert calculations.awaiting_effectiveness(car(), done)
    assert not calculations.awaiting_effectiveness(car(effectiveness_result="effective"), done)
    # No actions: nothing to review yet.
    assert not calculations.awaiting_effectiveness(car(), calculations.action_progress([], TODAY))


def test_aging_counts_reports_not_closed_by_days_open() -> None:
    reports = [
        car(request_date=TODAY - dt.timedelta(days=5)),
        car(request_date=TODAY - dt.timedelta(days=45)),
        car(request_date=TODAY - dt.timedelta(days=200)),
        car(request_date=TODAY - dt.timedelta(days=95), status=None),
        car(request_date=dt.date(2026, 1, 1), status="closed", date_closed=dt.date(2026, 2, 1)),
    ]
    buckets = calculations.aging(reports, TODAY)
    assert [b.label for b in buckets] == ["0–30 days", "31–60 days", "61–90 days", "Over 90 days"]
    assert [b.count for b in buckets] == [1, 1, 0, 2]


def test_step_states_follow_what_is_recorded() -> None:
    empty = calculations.step_states(car(due_date=None), calculations.action_progress([], TODAY), 0)
    assert [code for code, _, _ in empty] == [
        "identify",
        "contain",
        "investigate",
        "evaluate",
        "correct",
        "verify",
        "cost",
        "close",
    ]
    assert {state for _, _, state in empty} == {"not_started"}

    started = car(requested_by="Fixture", root_cause_code="method", material_loss=Decimal(0))
    progress = calculations.action_progress([action(status="complete")], TODAY)
    states = {code: state for code, _, state in calculations.step_states(started, progress, 1)}
    assert states["identify"] == "in_progress"
    assert states["investigate"] == "in_progress"
    assert states["correct"] == "complete"
    assert states["cost"] == "in_progress"
    assert states["close"] == "in_progress"


# Validation ------------------------------------------------------------------------


def _fields(**overrides: Any) -> CarCreate:
    return CarCreate.model_validate(
        {"subject": "Fixture: label mismatch", "requestDate": "2026-09-01", **overrides}
    )


def _closing(**overrides: Any) -> CarUpdate:
    return CarUpdate.model_validate(
        {
            "subject": "Fixture: label mismatch",
            "requestDate": "2026-09-01",
            "status": "closed",
            "dateClosed": "2026-10-05",
            "effectivenessResult": "effective",
            "version": 1,
            **overrides,
        }
    )


class _NoDatabase:
    """Validation looks users up only for a chosen user ID; these tests choose none."""

    @property
    def session(self) -> Any:
        raise AssertionError("no database in unit tests")


ACTOR = Actor(
    TESTER,
    dt.datetime(2026, 10, 6, 12, tzinfo=dt.UTC),
    permissions=None,
    user_id=TESTER_ID,
    name=TESTER_NAME,
)


def validated(fields: Any, **kwargs: Any) -> Any:
    return service._validated(_NoDatabase(), fields, actor=ACTOR, today=TODAY, **kwargs)  # type: ignore[arg-type]


def test_a_draft_needs_only_a_subject_and_request_date() -> None:
    values, why, references = validated(_fields())
    assert values["subject"] == "Fixture: label mismatch"
    assert values["status"] == "open"
    assert values["material_loss"] is None
    assert values["safety_hazard"] is None
    assert (why, references) == ((), ())
    assert values["closure_approved_by"] is None and values["reviewer"] is None


def test_text_is_trimmed_and_blank_rows_are_dropped() -> None:
    values, why, _ = validated(
        _fields(
            subject="  Fixture  ",
            assignedTo="   ",
            whySteps=[{"what": " "}, {"why": " Because "}],
        ),
    )
    assert values["subject"] == "Fixture"
    assert values["assigned_to"] is None and values["assigned_to_user_id"] is None
    assert [s.why for s in why] == ["Because"]


@pytest.mark.parametrize("field", ["requestedBy", "assignedTo", "containmentOwner"])
def test_free_text_people_are_refused(field: str) -> None:
    with pytest.raises(RecordRuleError) as raised:
        validated(_fields(**{field: "Somebody typed"}))
    assert (raised.value.error, raised.value.field) == ("invalid_person", field)


def test_a_recorded_legacy_name_is_kept_unchanged_and_not_linked() -> None:
    imported = car(assigned_to="J. Smith (from workbook)", assigned_to_user_id=None)
    update = CarUpdate.model_validate(
        {
            "subject": "Fixture",
            "requestDate": "2026-09-01",
            "status": "open",
            "assignedTo": "J. Smith (from workbook)",
            "version": 1,
        }
    )
    values, *_ = validated(update, current=imported)
    assert values["assigned_to"] == "J. Smith (from workbook)"
    assert values["assigned_to_user_id"] is None


def test_closure_approver_and_reviewer_come_from_the_session() -> None:
    values, *_ = validated(_closing(), current=car())
    assert (values["closure_approved_by"], values["closure_approved_by_user_id"]) == (
        TESTER_NAME,
        TESTER_ID,
    )
    assert (values["reviewer"], values["reviewer_user_id"]) == (TESTER_NAME, TESTER_ID)


def test_browser_supplied_approver_and_reviewer_are_rejected() -> None:
    for field in ("closureApprovedBy", "reviewer", "approvals"):
        with pytest.raises(ValidationError):
            _closing(**{field: "Someone else"})


def test_closure_approver_is_kept_while_closed_and_cleared_on_reopen() -> None:
    closed = car(
        status="closed",
        date_closed=dt.date(2026, 10, 5),
        effectiveness_result="effective",
        closure_approved_by="Original approver",
        closure_approved_by_user_id=None,
        reviewer="Original reviewer",
    )
    values, *_ = validated(_closing(), current=closed)
    assert values["closure_approved_by"] == "Original approver"
    assert values["reviewer"] == "Original reviewer"

    reopened = CarUpdate.model_validate(
        {
            "subject": "Fixture: label mismatch",
            "requestDate": "2026-09-01",
            "status": "open",
            "effectivenessResult": "effective",
            "version": 1,
        }
    )
    values, *_ = validated(reopened, current=closed)
    assert values["closure_approved_by"] is None
    assert values["reviewer"] == "Original reviewer"


@pytest.mark.parametrize(
    ("overrides", "error", "field"),
    [
        ({"subject": "  "}, "blank_subject", "subject"),
        ({"requestDate": "2026-10-10"}, "future_date", "requestDate"),
        ({"dueDate": "2026-08-31"}, "due_before_request", "dueDate"),
        ({"sourceCode": "rumour"}, "invalid_source", "sourceCode"),
        ({"departmentCode": "ca_operation"}, "invalid_department", "departmentCode"),
        ({"rootCauseCode": "quality"}, "invalid_root_cause", "rootCauseCode"),
        ({"dispositionCodes": ["blended"]}, "invalid_disposition", "dispositionCodes"),
        ({"startedTime": "08:00"}, "time_without_date", "startedOn"),
        ({"startedOn": "2026-09-02", "endedOn": "2026-09-01"}, "ended_before_started", "endedOn"),
        ({"reviewDate": "2026-10-10"}, "future_date", "reviewDate"),
        ({"dateClosed": "2026-10-01"}, "date_closed_not_closed", "dateClosed"),
        ({"references": [{"type": "invoice", "key": "1"}]}, "invalid_reference", "references"),
    ],
)
def test_report_rules(overrides: dict[str, Any], error: str, field: str) -> None:
    with pytest.raises(RecordRuleError) as raised:
        validated(_fields(**overrides))
    assert (raised.value.error, raised.value.field) == (error, field)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"dateClosed": None}, "date_closed_required"),
        ({"dateClosed": "2026-08-31"}, "closed_before_request"),
        ({"dateClosed": "2026-10-10"}, "future_date_closed"),
        ({"effectivenessResult": None}, "effectiveness_required"),
        ({"effectivenessResult": "not_effective"}, "follow_up_required"),
    ],
)
def test_closing_rules(overrides: dict[str, Any], error: str) -> None:
    with pytest.raises(RecordRuleError) as raised:
        validated(_closing(**overrides), current=car())
    assert raised.value.error == error


def test_a_car_cannot_close_with_outstanding_actions() -> None:
    actions = (action(status="complete"), action(status="on_hold"), action(status=None))
    with pytest.raises(RecordRuleError) as raised:
        validated(_closing(), actions=actions, current=car())
    assert raised.value.error == "actions_outstanding"
    assert "2 corrective action(s)" in raised.value.message

    values, *_ = validated(_closing(), actions=(action(status="complete"),), current=car())
    assert values["status"] == "closed"


def test_not_effective_closes_with_a_follow_up_reference() -> None:
    values, *_ = validated(
        _closing(effectivenessResult="not_effective", followUpReference="Q-2026-010"),
        current=car(),
    )
    assert values["follow_up_reference"] == "Q-2026-010"


def test_imported_older_form_values_stay_valid_when_unchanged() -> None:
    imported = car(
        status=None,
        source="legacy_import",
        department_code="ca_operation",
        disposition_codes=["blended"],
    )
    update = CarUpdate.model_validate(
        {
            "subject": "Fixture",
            "requestDate": "2026-09-01",
            "status": None,
            "departmentCode": "ca_operation",
            "dispositionCodes": ["blended", "rework"],
            "version": 1,
        }
    )
    values, *_ = validated(update, current=imported)
    assert values["department_code"] == "ca_operation"
    assert values["disposition_codes"] == ["blended", "rework"]
    assert values["status"] is None

    with pytest.raises(RecordRuleError) as raised:
        validated(update, current=car())
    assert raised.value.error == "invalid_department"

    no_status = CarUpdate.model_validate(
        {"subject": "Fixture", "requestDate": "2026-09-01", "status": None, "version": 1}
    )
    with pytest.raises(RecordRuleError) as raised:
        validated(no_status, current=car())
    assert raised.value.error == "status_required"


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"action": " "}, "blank_action"),
        ({"status": "complete"}, "completed_on_required"),
        ({"status": "complete", "completedOn": "2026-10-10"}, "future_date"),
        ({"status": "open", "completedOn": "2026-10-01"}, "completed_on_not_complete"),
    ],
)
def test_action_rules(fields: dict[str, Any], error: str) -> None:
    request = ActionFields.model_validate({"action": "Fixture action", **fields})
    with pytest.raises(RecordRuleError) as raised:
        service._validated_action(_NoDatabase(), request, today=TODAY)  # type: ignore[arg-type]
    assert raised.value.error == error


def test_an_imported_complete_action_without_a_date_can_still_be_edited() -> None:
    imported = action(status="complete", completed_on=None, owner="Fixture")
    request = ActionFields.model_validate(
        {"action": "Fixture action", "owner": "Fixture", "status": "complete"}
    )
    values = service._validated_action(
        _NoDatabase(),  # type: ignore[arg-type]
        request,
        today=TODAY,
        current=imported,
    )
    assert values["completed_on"] is None
    assert values["owner"] == "Fixture" and values["owner_user_id"] is None


@pytest.mark.parametrize(
    ("permissions", "owner", "allowed"),
    [
        ({Permission.CAR_COMPLETE_ACTION}, TESTER_ID, True),
        ({Permission.CAR_COMPLETE_ACTION}, None, False),
        ({Permission.CAR_COMPLETE_ACTION}, OTHER_ID, False),
        ({Permission.CAR_MANAGE_ACTIONS}, TESTER_ID, False),
        ({Permission.CAR_ADMIN}, OTHER_ID, True),
    ],
)
def test_only_the_owner_or_a_car_admin_completes_an_action(
    permissions: set[Permission], owner: Any, allowed: bool
) -> None:
    actor = Actor(TESTER, ACTOR.now, permissions=frozenset(permissions), user_id=TESTER_ID)
    assert service.can_complete_action(owner, actor) is allowed


def test_assigning_closing_and_reviewing_need_their_permissions() -> None:
    editor = Actor(
        TESTER, ACTOR.now, permissions=frozenset({Permission.CAR_EDIT}), user_id=TESTER_ID
    )
    base = {
        "assigned_to": None,
        "assigned_to_user_id": None,
        "effectiveness_result": None,
        "review_date": None,
        "status": "open",
    }
    service.check_permissions(base, car(), editor)
    for change, needed in [
        ({"assigned_to": "x", "assigned_to_user_id": OTHER_ID}, "car.assign"),
        ({"effectiveness_result": "effective"}, "car.reviewEffectiveness"),
        ({"status": "closed"}, "car.close"),
    ]:
        with pytest.raises(RecordForbiddenError, match=needed):
            service.check_permissions({**base, **change}, car(), editor)
    with pytest.raises(RecordForbiddenError, match="car.reopen"):
        service.check_permissions(base, car(status="closed"), editor)


@pytest.mark.parametrize(
    "overrides",
    [
        {"unknownField": "x"},
        {"subject": "x" * 201},
        {"status": "cancelled"},
        {"materialLoss": "-1"},
        {"approvals": [{"functionCode": "ceo", "name": "x"}]},
    ],
)
def test_schema_rejects_invalid_input(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _fields(**overrides)


# Dashboard --------------------------------------------------------------------------


def test_dashboard_figures_come_from_the_same_reports() -> None:
    rows = [
        CarRow(car(id=1, department_code="quality", source_code="customer_complaint"), ()),
        CarRow(
            car(
                id=2,
                department_code="quality",
                due_date=TODAY + dt.timedelta(days=3),
                material_loss=Decimal("100"),
                previous_occurrence=True,
            ),
            (action(status="complete"),),
        ),
        CarRow(
            car(
                id=3,
                status="closed",
                date_closed=dt.date(2026, 9, 20),
                effectiveness_result="effective",
                root_cause_code="method",
                material_loss=Decimal(0),
            ),
            (),
        ),
        CarRow(car(id=4, status=None, source="legacy_import", due_date=None), ()),
    ]
    result = dashboard.summary(rows, today=TODAY, due_soon_days=14)
    k = result.kpis
    assert (k.total, k.open, k.past_due, k.due_soon, k.awaiting_effectiveness, k.closed_ytd) == (
        4,
        3,
        1,
        1,
        1,
        1,
    )
    assert k.status_not_recorded == 1
    assert [(c.code, c.count) for c in result.by_status] == [
        ("open", 2),
        ("closed", 1),
        (None, 1),
    ]
    assert [(c.code, c.count) for c in result.by_department] == [("quality", 2), (None, 2)]
    assert [(c.code, c.count) for c in result.effectiveness] == [
        ("effective", 1),
        ("not_effective", 0),
        (None, 3),
    ]
    assert result.cost.total == Decimal(100)
    assert (result.cost.with_cost, result.cost.without_cost) == (2, 2)
    assert [c.car_number for c in result.repeat_cars] == ["Q-2026-900"]
    assert len(result.trend) == 12
    assert result.trend[-1].month == 10
    september = next(m for m in result.trend if m.month == 9)
    assert (september.opened, september.closed) == (4, 1)


def test_dashboard_without_costs_reports_no_total() -> None:
    result = dashboard.summary([CarRow(car(), ())], today=TODAY, due_soon_days=14)
    assert result.cost.total is None
    empty = dashboard.summary([], today=TODAY, due_soon_days=14)
    assert empty.kpis.total == 0
    assert all(b.count == 0 for b in empty.aging)


# Permissions ------------------------------------------------------------------------


def test_car_permissions_are_explicit_and_not_implied() -> None:
    car = {p for p in Permission if p.startswith("car.")}
    assert car == {
        Permission.CAR_VIEW,
        Permission.CAR_CREATE,
        Permission.CAR_EDIT,
        Permission.CAR_DELETE,
        Permission.CAR_ASSIGN,
        Permission.CAR_MANAGE_ACTIONS,
        Permission.CAR_COMPLETE_ACTION,
        Permission.CAR_REVIEW_EFFECTIVENESS,
        Permission.CAR_APPROVE,
        Permission.CAR_CLOSE,
        Permission.CAR_REOPEN,
        Permission.CAR_EXPORT,
        Permission.CAR_ADMIN,
    }
    assert {module_of(p) for p in car} == {"car"}


# Workbook parsing --------------------------------------------------------------------


def test_checked_boxes_are_read_from_the_disposition_row() -> None:
    text = "☐ Hold   ☒ Rework   ☐ Recycle   ☐ Dispose   ☐ Return   ☐ N/A   ☒ Other: Regrade"
    assert workbook._checked_labels(text) == ["Rework", "Other: Regrade"]
    assert workbook._checked_labels("☐ Hold ☐ Rework") == []


def test_risk_flags_need_exactly_one_box_checked() -> None:
    text = (
        "Safety hazard: ☐ Yes ☒ No     Environmental hazard: ☒ Yes ☐ No     "
        "Customer impact: ☐ Yes ☐ No"
    )
    assert workbook._risk_flag(text, "Safety hazard") is False
    assert workbook._risk_flag(text, "Environmental hazard") is True
    assert workbook._risk_flag(text, "Customer impact") is None


def test_dates_are_read_from_cells_or_a_leading_date_in_text() -> None:
    assert workbook._date(dt.datetime(2026, 7, 15)) == dt.date(2026, 7, 15)
    assert workbook._date("7/14/2026 \n(Repacks during campaign change)") == dt.date(2026, 7, 14)
    assert workbook._date("during the campaign") is None
    assert workbook._date("13/40/2026") is None


# Reviewed mapping ----------------------------------------------------------------------


def _mapping() -> legacy_import.CarMapping:
    return legacy_import.load_mapping(MAPPING)


def _entry(number: str) -> legacy_import.CarEntry:
    return next(e for e in _mapping().cars if e.car.car_number == number)


def test_mapping_holds_the_five_historical_cars_and_skips_the_template() -> None:
    mapping = _mapping()
    assert [e.car.car_number for e in mapping.cars] == [
        "Q-2026-001",
        "Q-2026-002",
        "Q-2026-003",
        "Q-2026-005",
        "Q-2026-006",
    ]
    assert [s.reason for s in mapping.skipped] == ["No CAR number (blank template)"]
    assert {e.layout for e in mapping.cars} == {"legacy", "rev2"}
    for entry in mapping.cars:
        assert entry.source_key == f"car-workbook/{entry.car.car_number}"
        assert legacy_import._problems(entry) == []


def test_mapping_does_not_invent_values() -> None:
    first = _entry("Q-2026-001")
    # The older form has no status, effectiveness result or customer-impact question.
    assert first.car.status is None
    assert first.car.effectiveness_result is None
    assert first.car.customer_impact is None
    # Zero entered on the form stays zero; blank stays not recorded.
    assert first.car.material_loss == Decimal(0)
    assert first.car.production_time_loss == Decimal(0)
    assert first.car.other_costs is None
    assert first.car.department_code is None
    assert first.car.assigned_to == "Cathi Eden; Tracy Andrus"
    (only,) = first.actions
    assert only.status is None and only.owner is None and only.target_date is None
    assert "(Tracy Andrus)" in only.action


def test_mapping_keeps_older_form_answers_as_legacy_fields() -> None:
    labels = {f.label: f.value for f in _entry("Q-2026-005").legacy_fields}
    assert labels["Root cause category"] == "quality"
    assert labels["Were there any equipment problems?"] == "No"
    assert _entry("Q-2026-005").car.root_cause_code is None

    repack = _entry("Q-2026-003")
    assert repack.car.department_code == "ca_operation"
    assert repack.car.started_on == dt.date(2026, 7, 14)
    assert repack.car.ended_on == dt.date(2026, 7, 16)
    texts = {f.label: f.value for f in repack.legacy_fields}
    assert "(Repacks during campaign change)" in texts["Time and date the problem began"]


def test_mapping_reads_the_rev2_form_section_by_section() -> None:
    entry = _entry("Q-2026-006")
    c = entry.car
    assert c.subject == "C-Grade Lot Blending 3411U and 3412 Lot 0"
    assert (c.requested_by, c.assigned_to) == ("Gabrielle Vita", "Jennifer Willingham")
    assert (c.request_date, c.due_date) == (dt.date(2026, 8, 21), dt.date(2026, 9, 21))
    assert (c.source_code, c.department_code, c.root_cause_code) == ("other", "other", "method")
    assert c.disposition_codes == ["rework"]
    assert (c.safety_hazard, c.environmental_hazard, c.customer_impact) == (False, False, False)
    assert (c.similar_issue_found, c.additional_action_required) == (None, True)
    assert c.training_completed is True
    assert c.status == "open"
    assert c.effectiveness_result is None and c.reviewer is None
    assert [a.status for a in entry.actions] == ["complete"] * 4
    assert [a.owner for a in entry.actions] == [
        "Quality",
        "Process Manager",
        "Operations Supervisor",
        "Operations Supervisor",
    ]
    assert len(c.why_steps) == 4
    assert c.complaint_number == "Q-2026-006"
    assert c.approvals == []
    assert any("Why-Why" in w for w in entry.warnings)


def test_mapping_carries_no_values_the_schema_rejects(tmp_path: Path) -> None:
    data = json.loads(MAPPING.read_text(encoding="utf-8"))
    data["cars"][0]["car"]["carNumber"] = "2026-001"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        legacy_import.load_mapping(path)


def test_plan_inserts_new_reports_and_blocks_on_conflicts() -> None:
    mapping = _mapping()
    plan = legacy_import.plan_import(mapping, {}, set())
    assert [e.car.car_number for e in plan.inserts] == [e.car.car_number for e in mapping.cars]
    assert not plan.blocked

    # A number already used by a report not imported from this workbook.
    conflict = legacy_import.plan_import(mapping, {}, {"Q-2026-006"})
    assert conflict.number_conflicts == ["Q-2026-006"]
    assert conflict.blocked


def test_plan_is_idempotent_and_reports_differences() -> None:
    mapping = _mapping()
    stored = {}
    for entry in mapping.cars:
        values = legacy_import.car_values(mapping, entry)
        stored[entry.source_key] = car(**{k: v for k, v in values.items() if k in Car.__table__.c})
    plan = legacy_import.plan_import(mapping, stored, set())
    assert plan.empty and not plan.blocked
    assert len(plan.unchanged) == 5

    stored["car-workbook/Q-2026-002"].subject = "Edited subject"
    changed = legacy_import.plan_import(mapping, stored, set())
    assert changed.blocked
    assert [(n, f) for n, f, *_ in changed.differing] == [("Q-2026-002", "subject")]


def test_migration_notes_name_the_source_file() -> None:
    mapping = _mapping()
    notes = legacy_import.migration_notes(mapping, _entry("Q-2026-003"))
    assert "Q-2026-003 CAR - 3522 Repack Labels.xlsx" in notes
    assert "older CAR form" in notes
