"""Process Safety Management without a database: figures, worksheet parsing,
the reviewed 2026 mapping, request validation and email delivery rules.

Workbooks built here are fixtures (labelled "Fixture"); the real workbook is
read only when present on the machine, never modified."""

import datetime as dt
import io
from pathlib import Path

import pytest
from openpyxl import Workbook
from pydantic import ValidationError

from app.core import mail
from app.core.config import Settings
from app.safety.psm import metrics, pha_import
from app.safety.psm.metrics import ActionView, RecommendationView
from app.safety.psm.reference import MAX_SHORT, MAX_TEXT
from app.safety.psm.schemas import (
    AcceptRequest,
    ActionUpdate,
    ClosureRequest,
    RecommendationCreate,
    RejectRequest,
    StatusChange,
)

TODAY = dt.date(2026, 10, 12)
ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "import_templates" / "psm_pha_2026_300_400_600.mapping.json"
WORKBOOK = ROOT.parents[1] / "docs" / "PSM Dashboard 1.xlsx"


def _action(status: str = "not_started", **values: object) -> ActionView:
    fields: dict[str, object] = {
        "id": 1,
        "action_number": "PSM-ACT-2026-001",
        "status": status,
        "department_id": None,
        "department": None,
        "owner_key": None,
        "owner": None,
        "due_date": None,
        "created_on": TODAY,
    }
    fields.update(values)
    return ActionView(**fields)  # type: ignore[arg-type]


def _rec(
    disposition: str = "pending_review",
    risks: tuple[str, ...] = ("low",),
    action: ActionView | None = None,
    **values: object,
) -> RecommendationView:
    return RecommendationView(
        id=values.pop("id", 1),  # type: ignore[arg-type]
        study_id=1,
        display_id="PHA-2026-001",
        disposition=disposition,
        scenario_risks=risks,
        action=action,
        **values,  # type: ignore[arg-type]
    )


# Figures -------------------------------------------------------------------------------


def test_governing_risk_is_the_highest_scenario_risk() -> None:
    assert metrics.governing_risk(["low", "medium", "low"]) == "medium"
    assert metrics.governing_risk(["low", "high"]) == "high"
    assert metrics.governing_risk([]) is None


def test_zero_data_gives_zero_counts_and_no_percentage() -> None:
    k = metrics.kpis([], TODAY)
    assert k.total == 0 and k.closed == 0
    assert k.closure_pct is None
    pending_only = metrics.kpis([_rec()], TODAY)
    assert pending_only.closure_pct is None
    assert metrics.lifecycle([])["identified"] == 0


def test_overdue_excludes_closed_and_missing_due_dates() -> None:
    late = _action("in_progress", due_date=TODAY - dt.timedelta(days=1))
    closed = _action("closed", due_date=TODAY - dt.timedelta(days=30))
    unscheduled = _action("in_progress")
    assert metrics.is_overdue(late, TODAY)
    assert not metrics.is_overdue(closed, TODAY)
    assert not metrics.is_overdue(unscheduled, TODAY)
    assert metrics.needs_scheduling(unscheduled)
    assert not metrics.needs_scheduling(closed)
    assert metrics.due_state(_action(due_date=TODAY), TODAY) == "due_7"
    assert metrics.due_state(_action(due_date=TODAY + dt.timedelta(days=8)), TODAY) == "due_30"
    assert metrics.due_state(unscheduled, TODAY) == "no_due_date"


def test_risk_overview_separates_scenarios_from_recommendations() -> None:
    recs = [
        _rec(risks=("low", "medium", "medium"), id=1),
        _rec(risks=("low",), id=2),
    ]
    assert metrics.scenario_risks(recs) == {"high": 0, "medium": 2, "low": 2}
    assert metrics.governing_risks(recs) == {"high": 0, "medium": 1, "low": 1}


def test_drafts_and_archived_recommendations_are_left_out_of_figures() -> None:
    recs = [_rec(id=1), _rec(id=2, is_draft=True), _rec(id=3, archived=True)]
    assert metrics.kpis(recs, TODAY).total == 1
    assert metrics.scenario_risks(recs)["low"] == 1


def test_lifecycle_counts_every_stage_reached_and_rejected_separately() -> None:
    assigned = _action("in_progress", owner_key="ext:x", owner="X", due_date=TODAY)
    recs = [
        _rec("pending_review", id=1),
        _rec("rejected", id=2),
        _rec("accepted", action=_action(), id=3),
        _rec("accepted", action=assigned, id=4),
        _rec("accepted", action=_action("closed"), id=5),
    ]
    stages = metrics.lifecycle(recs)
    assert stages["identified"] == 5
    assert stages["reviewed"] == 4
    assert stages["accepted"] == 3
    assert stages["assigned"] == 1
    assert stages["in_progress"] == 2
    assert stages["verification"] == 1
    assert stages["closed"] == 1
    assert stages["rejected"] == 1


def test_matrix_places_recommendations_by_governing_risk_and_action_status() -> None:
    recs = [
        _rec("pending_review", ("medium",), id=1),
        _rec("accepted", ("low", "medium"), _action("in_progress"), id=2),
        _rec("rejected", ("high",), id=3),
    ]
    cells = metrics.matrix(recs)
    assert cells["medium"]["no_action"] == 1
    assert cells["medium"]["in_progress"] == 1
    assert sum(cells["high"].values()) == 0


def test_distribution_includes_unassigned_and_external_owners() -> None:
    recs = [
        _rec("accepted", action=_action(), id=1),
        _rec(
            "accepted",
            action=_action(
                "in_progress",
                owner_key="ext:pat",
                owner="Pat Doe",
                due_date=TODAY - dt.timedelta(1),
            ),
            id=2,
        ),
        _rec("accepted", action=_action("closed", owner_key="ext:pat", owner="Pat Doe"), id=3),
    ]
    loads = {load.owner: load for load in metrics.distribution(recs, TODAY)}
    assert loads[metrics.UNASSIGNED].not_started == 1
    assert loads["Pat Doe"].in_progress == 1
    assert loads["Pat Doe"].overdue == 1
    assert loads["Pat Doe"].total_active == 1


def test_aging_buckets_count_open_actions_from_creation() -> None:
    recs = [
        _rec("accepted", action=_action(created_on=TODAY - dt.timedelta(days=45)), id=1),
        _rec("accepted", action=_action(created_on=TODAY - dt.timedelta(days=200)), id=2),
        _rec("accepted", action=_action("closed", created_on=TODAY - dt.timedelta(days=5)), id=3),
    ]
    assert metrics.aging(recs, TODAY) == {"0_30": 0, "31_60": 1, "61_90": 0, "90_plus": 1}


def test_needs_attention_reasons() -> None:
    action = _action(due_date=TODAY - dt.timedelta(days=1), failed_notification=True)
    reasons = metrics.needs_attention(action, TODAY)
    assert {"overdue", "missing_owner", "missing_department", "notification_failed"} <= set(reasons)
    assert metrics.needs_attention(_action("closed"), TODAY) == []


# Requests ------------------------------------------------------------------------------


def test_rejection_needs_a_substantive_justification() -> None:
    with pytest.raises(ValidationError):
        RejectRequest.model_validate({"version": 1, "justification": "  no  "})
    ok = RejectRequest.model_validate(
        {"version": 1, "justification": "  Existing PSH interlock already covers this case.  "}
    )
    assert ok.justification == "Existing PSH interlock already covers this case."


def test_a_recommendation_needs_a_scenario_unless_saved_as_a_draft() -> None:
    base = {"studyId": 1, "areaEquipment": "V-1", "recommendationText": "Fixture text"}
    with pytest.raises(ValidationError):
        RecommendationCreate.model_validate(base)
    assert RecommendationCreate.model_validate({**base, "isDraft": True}).is_draft
    with pytest.raises(ValidationError):
        RecommendationCreate.model_validate(
            {**base, "scenarios": [{"event": "e", "cause": "c", "consequence": "", "risk": "low"}]}
        )


def test_status_cannot_be_set_to_closed_or_pending_verification_directly() -> None:
    for target in ("closed", "pending_verification", "rejected"):
        with pytest.raises(ValidationError):
            StatusChange.model_validate({"version": 1, "status": target})
    assert "status" not in ActionUpdate.model_fields


def test_closure_request_needs_a_summary() -> None:
    with pytest.raises(ValidationError):
        ClosureRequest.model_validate({"version": 1, "summary": " "})


def test_acceptance_needs_confirmation_and_takes_external_owner_email() -> None:
    with pytest.raises(ValidationError):
        AcceptRequest.model_validate({"version": 1})
    ok = AcceptRequest.model_validate(
        {"version": 1, "confirm": True, "ownerName": "Pat Doe", "ownerEmail": " Pat@Example.COM "}
    )
    assert ok.owner_email == "pat@example.com"
    assert ok.department_id is None and ok.due_date is None


def test_optional_text_accepts_explicit_nulls_and_still_limits_length() -> None:
    blank = AcceptRequest.model_validate(
        {
            "version": 1,
            "confirm": True,
            "departmentId": None,
            "ownerUserId": None,
            "ownerName": None,
            "ownerEmail": None,
            "dueDate": None,
            "task": None,
        }
    )
    assert blank.owner_name is None and blank.owner_email is None and blank.task is None
    assert AcceptRequest.model_validate({"version": 1, "confirm": True, "task": "  "}).task is None
    too_long = (("task", "x" * (MAX_TEXT + 1)), ("ownerName", "x" * (MAX_SHORT + 1)))
    for field, value in (*too_long, ("ownerEmail", "nope")):
        with pytest.raises(ValidationError):
            AcceptRequest.model_validate({"version": 1, "confirm": True, field: value})


# Worksheet parsing ---------------------------------------------------------------------

FIXTURE_SHEET = "Fixture PHA"
FIXTURE_PROFILE = pha_import.StudyProfile(
    study_code="FIXTURE-PHA",
    title="Fixture PHA",
    year=2003,
    study_type="pha",
    recommendation_prefix="FIXTURE-2003",
    area_codes=("300",),
    expected=pha_import.Expected(
        recommendations=2,
        scenarios=3,
        risks={"high": 0, "medium": 1, "low": 2},
        per_recommendation={1: 2, 2: 1},
    ),
)
HEADER = [
    "#",
    "Area/ Equipment ",
    "Recomendation ",
    "Consequence",
    "Cause",
    "Event ",
    "Node",
    "Priority/ Risk",
    "Accepted (Y/N)",
    "Task/ Justification",
    "Department ",
    "Owner ",
    "Status",
    "Notes ",
]


def _workbook(rows: list[list[object]], footer: bool = True) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = FIXTURE_SHEET
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    if footer:
        sheet.append([])
        for label in ("Total", "Rejected", "Accepted ", "Open ", "Closed ", "In-Progress "):
            sheet.append([None, label, 2 if label == "Total" else None])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


GOOD_ROWS: list[list[object]] = [
    [1, "V-1 ", "Fixture recommendation one ", "Cons A", "Cause A", "1.1.", "10. Node A", "Low"],
    [None, "V-2", None, "Cons B", "Cause B", "1.2.", "11. Node B", "Medium "],
    [2, "R-1", "Fixture  recommendation two", "Cons C", "Cause C", "2.1.", "12. Node C", "low"],
]


def _extract(content: bytes) -> pha_import.PhaMapping:
    return pha_import.extract(content, "Fixture.xlsx", FIXTURE_SHEET, FIXTURE_PROFILE)


def test_continuation_rows_become_scenarios_of_one_recommendation() -> None:
    mapping = _extract(_workbook(GOOD_ROWS))
    first, second = mapping.recommendations
    assert [s.row for s in first.scenarios] == [2, 3]
    assert first.area_equipment == "V-1"
    assert first.scenarios[1].area_equipment == "V-2"
    assert first.scenarios[1].node == "11. Node B"
    assert first.scenarios[1].risk == "medium"
    assert first.scenarios[1].risk_source == "Medium "
    # Text keeps its internal spacing; only the ends are trimmed. Raw cells are kept.
    assert second.recommendation_text == "Fixture  recommendation two"
    assert first.scenarios[0].cells["C2"] == "Fixture recommendation one "
    assert mapping.trimmed_values >= 3


def test_blank_node_and_equipment_inherit_within_the_recommendation() -> None:
    rows = [list(r) for r in GOOD_ROWS]
    rows[1][1] = None
    rows[1][6] = None
    first = _extract(_workbook(rows)).recommendations[0]
    assert first.scenarios[1].area_equipment == "V-1"
    assert first.scenarios[1].node == "10. Node A"


def test_footer_labels_are_never_imported() -> None:
    mapping = _extract(_workbook(GOOD_ROWS))
    texts = {r.area_equipment for r in mapping.recommendations}
    assert not texts & {"Total", "Rejected", "Accepted", "Open", "Closed", "In-Progress"}
    assert len(mapping.recommendations) == 2


def test_validation_lists_every_problem_and_imports_nothing() -> None:
    rows = [list(r) for r in GOOD_ROWS]
    rows[0][7] = "Severe"
    rows[2] += [None, None, "Operations"]
    with pytest.raises(pha_import.ImportValidationError) as raised:
        _extract(_workbook(rows))
    errors = " ".join(raised.value.errors)
    assert "Severe" in errors
    assert "K4" in errors


def test_counts_must_reconcile() -> None:
    with pytest.raises(pha_import.ImportValidationError) as raised:
        _extract(_workbook(GOOD_ROWS[:2]))
    assert any("expected 2" in e for e in raised.value.errors)


def test_the_reviewed_2026_mapping_meets_the_reconciliation() -> None:
    mapping = pha_import.PhaMapping.model_validate_json(MAPPING.read_text(encoding="utf-8"))
    assert pha_import.validate(mapping) == []
    scenarios = [s for r in mapping.recommendations for s in r.scenarios]
    assert len(mapping.recommendations) == 20
    assert len(scenarios) == 30
    assert sum(s.risk == "low" for s in scenarios) == 12
    assert sum(s.risk == "medium" for s in scenarios) == 18
    assert sum(s.risk == "high" for s in scenarios) == 0
    per = {r.number: len(r.scenarios) for r in mapping.recommendations}
    assert per[1] == 3 and per[2] == 2 and per[6] == 2 and per[10] == 4
    assert per[16] == per[17] == per[18] == 2
    assert mapping.source.sheet_name == "2026 PHA - 300,400,600"


@pytest.mark.skipif(not WORKBOOK.exists(), reason="the source workbook is not on this machine")
def test_the_workbook_still_extracts_to_the_reviewed_mapping() -> None:
    content = WORKBOOK.read_bytes()
    mapping = pha_import.extract(content, WORKBOOK.name)
    reviewed = pha_import.PhaMapping.model_validate_json(MAPPING.read_text(encoding="utf-8"))
    assert mapping == reviewed


# Email -------------------------------------------------------------------------------------


def test_mail_is_off_unless_configured() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert not settings.mail_enabled
    with pytest.raises(mail.MailNotConfiguredError):
        mail.send(settings, mail.OutgoingMail("a@example.com", None, "s", "b"))


def test_an_unreachable_mail_server_is_a_delivery_error_without_secrets() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        smtp_host="127.0.0.1",
        smtp_port=9,
        smtp_from="psm@fixture.test",
        smtp_username="fixture",
        smtp_password="fixture-secret-value",  # noqa: S106 - fixture, not a credential
        smtp_timeout_seconds=1,
    )
    with pytest.raises(mail.MailDeliveryError) as raised:
        mail.send(settings, mail.OutgoingMail("a@example.com", None, "s", "b"))
    assert "fixture-secret-value" not in str(raised.value)
