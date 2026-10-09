"""Read CAR workbooks into import entries (development machine only: needs openpyxl).

Two layouts exist:

- ``rev2``: form QMS-006-1 Rev. 2 (sheet ``CAR`` with ``CAR NUMBER`` in A4).
  Its sections map one-to-one onto the CAR fields.
- ``legacy``: the older CAR form (``CAR#`` in A2). Its answers that have a
  current field are mapped; the rest (equipment questions, signatures, values
  outside the current lists) are kept verbatim as legacy fields.

Nothing is inferred: a blank cell stays null, a value that does not match a
controlled list exactly (ignoring case) is kept as a legacy field, and free
text is kept verbatim. A file with no CAR number (the blank template) is
skipped. Workbooks are opened read-only and never written.
"""

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.quality.car.reference import (
    ACTION_STATUSES,
    APPROVAL_FUNCTIONS,
    CAR_STATUSES,
    DEPARTMENTS,
    DISPOSITIONS,
    EFFECTIVENESS_RESULTS,
    LEGACY_DEPARTMENTS,
    LEGACY_DISPOSITIONS,
    ROOT_CAUSE_CATEGORIES,
    SOURCES,
)

_NUMBER_AND_SUBJECT = re.compile(r"^\s*([A-Z]{1,5}-[0-9]{4}-[0-9]{3,6})\b[\s:–—-]*(.*)$", re.S)
_LEADING_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\b")
_CHECKED = "☒"
# Older-form disposition answers with a current equivalent.
_LEGACY_DISPOSITION_CODES = {
    "reworked": "rework",
    "recycled": "recycle",
    "disposed": "dispose",
    "n/a": "not_applicable",
    "other": "other",
    "blended": "blended",
    "placed in totes": "placed_in_totes",
    "isolated in storage tank": "isolated_in_tank",
}


@dataclass
class Extracted:
    """One workbook's import entry, before it is written to the mapping file."""

    source_file: str
    sha256: str
    layout: str
    car: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    legacy_fields: list[dict[str, str]] = field(default_factory=list)
    cells: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class _Sheet:
    def __init__(self, sheet: Any, name: str, out: Extracted) -> None:
        self.sheet = sheet
        self.name = name
        self.out = out

    def raw(self, cell: str) -> Any:
        return _clean(self.sheet[cell].value)

    def cell_name(self, cell: str) -> str:
        return f"{self.name}!{cell}"

    def text(self, target: str, cell: str) -> str | None:
        value = self.raw(cell)
        if value is None:
            return None
        text = value if isinstance(value, str) else _plain(value)
        self.out.car[target] = text
        self.out.cells[target] = self.cell_name(cell)
        return text

    def date(self, target: str, cell: str, label: str) -> dt.date | None:
        value = self.raw(cell)
        if value is None:
            return None
        parsed = _date(value)
        if parsed is None:
            self.out.legacy_fields.append({"label": label, "value": _plain(value)})
            self.out.warnings.append(f"{label}: '{_plain(value)}' is not a date; kept as written")
            return None
        if isinstance(value, str):
            self.out.legacy_fields.append({"label": label, "value": value})
            self.out.notes.append(
                f"{label}: the date {parsed:%m/%d/%Y} was taken from the text '{value}', "
                "which is kept as written"
            )
        self.out.car[target] = parsed.isoformat()
        self.out.cells[target] = self.cell_name(cell)
        if isinstance(value, dt.datetime) and value.time() != dt.time.min:
            if target in ("started_on", "ended_on"):
                self.out.car[target.replace("_on", "_time")] = value.time().isoformat()
            else:
                self.out.legacy_fields.append({"label": f"{label} (time)", "value": _plain(value)})
        return parsed

    def flag(self, target: str, cell: str, label: str) -> bool | None:
        value = self.raw(cell)
        if value is None:
            return None
        answer = _yes_no(value)
        if answer is None:
            self._legacy(label, value)
            return None
        self.out.car[target] = answer
        self.out.cells[target] = self.cell_name(cell)
        return answer

    def money(self, target: str, cell: str, label: str) -> Decimal | None:
        value = self.raw(cell)
        if value is None:
            return None
        try:
            amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
        except InvalidOperation:
            self._legacy(label, value)
            return None
        if amount < 0:
            self._legacy(label, value)
            return None
        self.out.car[target] = format(amount.normalize(), "f")
        self.out.cells[target] = self.cell_name(cell)
        return amount

    def code(
        self,
        target: str,
        cell: str,
        label: str,
        choices: dict[str, str],
        extra: dict[str, str] | None = None,
    ) -> str | None:
        value = self.raw(cell)
        if value is None:
            return None
        lookup = {v.lower(): k for k, v in choices.items()}
        lookup.update(extra or {})
        code = lookup.get(_plain(value).lower())
        if code is None:
            self._legacy(label, value)
            self.out.warnings.append(
                f"{label}: '{_plain(value)}' is not on the current list; kept as written"
            )
            return None
        self.out.car[target] = code
        self.out.cells[target] = self.cell_name(cell)
        return code

    def legacy(self, label: str, cell: str) -> None:
        value = self.raw(cell)
        if value is not None:
            self._legacy(label, value)

    def _legacy(self, label: str, value: Any) -> None:
        self.out.legacy_fields.append({"label": label, "value": _plain(value)})


def _plain(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time.min else value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        match = _LEADING_DATE.match(value)
        if match:
            month, day, year = (int(g) for g in match.groups())
            try:
                return dt.date(year, month, day)
            except ValueError:
                return None
    return None


def _yes_no(value: Any) -> bool | None:
    text = _plain(value).lower()
    return {"yes": True, "no": False}.get(text)


def _checked_labels(text: str) -> list[str]:
    """Labels following a checked box: '☐ Hold ☒ Rework' -> ['Rework']."""
    return [m.group(1).strip() for m in re.finditer(r"☒\s*([^☐☒]+?)(?=\s*(?:☐|☒|$))", text)]


def _risk_flag(text: str, label: str) -> bool | None:
    match = re.search(rf"{re.escape(label)}:\s*([☐☒])\s*Yes\s*([☐☒])\s*No", text, re.I)
    if match is None:
        return None
    yes, no = match.group(1) == _CHECKED, match.group(2) == _CHECKED
    if yes == no:
        return None
    return yes


# Rev. 2 ---------------------------------------------------------------------------


def _rev2(book: Any, out: Extracted) -> None:
    s = _Sheet(book["CAR"], "CAR", out)
    header = s.raw("C4")
    if header is None:
        out.skipped = "No CAR number (blank template)"
        return
    match = _NUMBER_AND_SUBJECT.match(_plain(header))
    if match is None:
        out.skipped = f"CAR number not recognised in '{_plain(header)}'"
        return
    out.car["car_number"] = match.group(1)
    out.cells["car_number"] = s.cell_name("C4")
    subject = _clean(match.group(2))
    if subject is None:
        out.skipped = "No subject: the CAR NUMBER cell holds only the number"
        return
    out.car["subject"] = subject
    out.cells["subject"] = s.cell_name("C4")
    out.notes.append("The subject is the text after the CAR number in the CAR NUMBER cell.")

    s.text("requested_by", "C5")
    s.date("request_date", "F5", "Request date")
    s.text("assigned_to", "C6")
    s.date("due_date", "F6", "Due date")
    # 1
    s.code("source_code", "C9", "Source of CAR", SOURCES)
    s.code("department_code", "F9", "Department", DEPARTMENTS)
    s.date("started_on", "C10", "Date/time started")
    s.date("ended_on", "F10", "Date/time ended")
    s.flag("previous_occurrence", "C11", "Previous occurrence?")
    previous = s.raw("F11")
    if previous is not None:
        out.car["previous_car"] = _plain(previous)
        out.cells["previous_car"] = s.cell_name("F11")
    s.text("nonconformity_description", "A13")
    s.text("objective_evidence", "A17")
    # 2
    s.text("immediate_actions", "A22")
    s.text("containment_owner", "C25")
    s.date("containment_completed_on", "F25", "Containment completion date")
    disposition = s.raw("C26")
    if disposition is not None:
        codes: list[str] = []
        labels = {v.lower(): k for k, v in DISPOSITIONS.items()}
        for label in _checked_labels(_plain(disposition)):
            name, _, other = label.partition(":")
            code = labels.get(name.strip().lower())
            if code is None:
                s._legacy("Material disposition", label)
                continue
            codes.append(code)
            if code == "other" and _clean(other):
                out.car["disposition_other"] = other.strip()
        if codes:
            out.car["disposition_codes"] = codes
            out.cells["disposition_codes"] = s.cell_name("C26")
    risks = s.raw("C27")
    if risks is not None:
        for target, label in (
            ("safety_hazard", "Safety hazard"),
            ("environmental_hazard", "Environmental hazard"),
            ("customer_impact", "Customer impact"),
        ):
            answer = _risk_flag(_plain(risks), label)
            if answer is not None:
                out.car[target] = answer
                out.cells[target] = s.cell_name("C27")
    # 3
    s.text("incident_type", "C31")
    s.code("root_cause_code", "F31", "Root cause category", ROOT_CAUSE_CATEGORIES)
    s.text("equipment_involved", "C32")
    s.text("work_order_number", "F32")
    s.text("investigation_summary", "A34")
    s.text("true_root_cause", "A39")
    # 4
    s.text("similar_nonconformities", "A46")
    s.flag("similar_issue_found", "C49", "Similar issue found?")
    s.flag("additional_action_required", "F49", "Additional action required?")
    # 5
    status_codes = {v.lower(): k for k, v in ACTION_STATUSES.items()}
    for row in range(53, 57):
        action = s.raw(f"A{row}")
        owner, target, status = s.raw(f"D{row}"), s.raw(f"E{row}"), s.raw(f"F{row}")
        if action is None:
            if any(v is not None for v in (owner, target, status)):
                out.warnings.append(f"Action row {row - 52} has no action text; not imported")
                for label, value in (("owner", owner), ("target date", target), ("status", status)):
                    if value is not None:
                        s._legacy(f"Action row {row - 52} {label}", value)
            continue
        entry: dict[str, Any] = {"action": _plain(action), "owner": None, "target_date": None}
        if owner is not None:
            entry["owner"] = _plain(owner)
        if target is not None:
            day = _date(target)
            if day is None:
                s._legacy(f"Action {row - 52} target date", target)
            else:
                entry["target_date"] = day.isoformat()
        entry["status"] = status_codes.get(_plain(status).lower()) if status else None
        if status is not None and entry["status"] is None:
            s._legacy(f"Action {row - 52} status", status)
        entry["completed_on"] = None
        entry["cells"] = [s.cell_name(f"{c}{row}") for c in "ADEF"]
        out.actions.append(entry)
    if any(a["status"] == "complete" for a in out.actions):
        out.notes.append(
            "Actions marked Complete on the form have no completion date of their own; "
            "the completion date is left not recorded."
        )
    s.text("procedures_revised", "C57")
    s.flag("training_completed", "F57", "Training completed?")
    s.text("supporting_documents", "C58")
    s.date("plan_completed_on", "F58", "Actual completion date")
    # 6
    s.text("success_criteria", "A63")
    s.text("effectiveness_evidence", "A67")
    s.text("reviewer", "C70")
    s.date("review_date", "F70", "Review date")
    s.code("effectiveness_result", "C71", "Effectiveness result", EFFECTIVENESS_RESULTS)
    s.text("follow_up_reference", "F71")
    # 7
    entered = [
        s.money("material_loss", "C74", "Material loss ($)"),
        s.money("production_time_loss", "F74", "Production time loss ($)"),
        s.money("other_costs", "C75", "Other costs ($)"),
    ]
    _check_total(s, "F75", "Total cost ($)", entered)
    # 8
    functions = {v.lower(): k for k, v in APPROVAL_FUNCTIONS.items()}
    approvals: list[dict[str, Any]] = []
    for row in (79, 80, 81):
        for function_cell, name_cell, date_cell in (("A", "B", "C"), ("D", "E", "F")):
            function = s.raw(f"{function_cell}{row}")
            name = s.raw(f"{name_cell}{row}")
            day = s.raw(f"{date_cell}{row}")
            if name is None and day is None:
                continue
            code = functions.get(_plain(function).lower()) if function else None
            if code is None or name is None:
                s._legacy(
                    f"Approval {_plain(function) if function else row}", f"{name or ''} {day or ''}"
                )
                continue
            approved_on = _date(day) if day is not None else None
            approvals.append(
                {
                    "function_code": code,
                    "name": _plain(name),
                    "approved_on": approved_on.isoformat() if approved_on else None,
                }
            )
    if approvals:
        out.car["approvals"] = approvals
    s.code("status", "C82", "CAR status", CAR_STATUSES)
    s.date("date_closed", "F82", "Date closed")
    s.text("closure_approved_by", "C83")
    if "status" not in out.car:
        out.car["status"] = None
    _why_why(book, out)


def _check_total(s: _Sheet, cell: str, label: str, entered: list[Decimal | None]) -> None:
    value = s.raw(cell)
    if value is None:
        return
    try:
        stated = Decimal(str(value).replace("$", "").replace(",", ""))
    except InvalidOperation:
        s._legacy(label, value)
        return
    calculated = sum((v for v in entered if v is not None), Decimal(0))
    if abs(stated - calculated) >= Decimal("0.01"):
        s._legacy(label, value)
        s.out.warnings.append(
            f"{label} on the form ({stated}) differs from the sum of the cost lines "
            f"({calculated}); the total is calculated, the form's value is kept as written"
        )


def _why_why(book: Any, out: Extracted) -> None:
    if "Why Why Worksheet" not in book.sheetnames:
        return
    w = _Sheet(book["Why Why Worksheet"], "Why Why Worksheet", out)
    w.text("complaint_number", "B4")
    w.date("date_reported", "C7", "Why-Why date reported")
    w.text("dr_number", "I7")
    w.text("material_name", "C8")
    w.text("po_number", "I8")
    w.text("supplier", "C9")
    w.date("date_delivered", "I9", "Why-Why date delivered")
    w.text("production_lot", "C10")
    quantity = w.raw("I10") or w.raw("K10")
    if quantity is not None:
        out.car["quantity_affected"] = _plain(quantity)
        out.cells["quantity_affected"] = w.cell_name("I10" if w.raw("I10") else "K10")
    steps = []
    for row in (15, 20, 25, 30):
        values = {
            "what": w.raw(f"A{row}"),
            "why": w.raw(f"C{row}"),
            "root_cause": w.raw(f"H{row}"),
            "countermeasure": w.raw(f"L{row}"),
            "who": w.raw(f"N{row}"),
        }
        day = w.raw(f"O{row}")
        if all(v is None for v in values.values()) and day is None:
            continue
        step: dict[str, Any] = {
            k: (_plain(v) if v is not None else None) for k, v in values.items()
        }
        parsed = _date(day) if day is not None else None
        if day is not None and parsed is None:
            w._legacy(f"Why-Why row {len(steps) + 1} date", day)
        step["target_date"] = parsed.isoformat() if parsed else None
        steps.append(step)
    if steps:
        out.car["why_steps"] = steps
        action_dates = {a.get("target_date") for a in out.actions}
        step_dates = {s["target_date"] for s in steps if s["target_date"]}
        if out.actions and step_dates and not step_dates <= action_dates:
            out.warnings.append(
                "The Why-Why worksheet dates differ from the corrective action target dates; "
                "both are imported as written"
            )


# Older form -------------------------------------------------------------------------


def _legacy_form(book: Any, out: Extracted) -> None:
    s = _Sheet(book["CAR"], "CAR", out)
    number = s.raw("B2")
    if number is None:
        out.skipped = "No CAR number"
        return
    if _NUMBER_AND_SUBJECT.match(_plain(number)) is None:
        out.skipped = f"CAR number not recognised: '{_plain(number)}'"
        return
    out.car["car_number"] = _plain(number)
    out.cells["car_number"] = s.cell_name("B2")
    if s.text("subject", "D2") is None:
        out.skipped = "No subject"
        return
    s.text("assigned_to", "B3")
    s.text("requested_by", "B4")
    s.date("request_date", "F3", "Request date")
    s.date("due_date", "F4", "Due date")
    s.text("incident_type", "E8")
    s.flag("previous_occurrence", "E9", "Is this problem a repeatable incident?")
    original = s.raw("E10")
    if original is not None:
        out.car["previous_car"] = _plain(original)
        out.cells["previous_car"] = s.cell_name("E10")
    s.date("started_on", "E11", "Time and date the problem began")
    s.date("ended_on", "E12", "Time and date the problem ended")
    s.code(
        "department_code",
        "E13",
        "Department",
        {**DEPARTMENTS, **LEGACY_DEPARTMENTS},
    )
    entered = [
        s.money("material_loss", "E17", "Cost of material lost"),
        s.money("production_time_loss", "E18", "Cost of production time lost"),
        s.money("other_costs", "E19", "Miscellaneous costs"),
    ]
    _check_total(s, "E20", "Total costs", entered)
    disposition = s.raw("E24")
    if disposition is not None:
        code = _LEGACY_DISPOSITION_CODES.get(_plain(disposition).lower())
        if code is None:
            s._legacy("Disposition of material", disposition)
        else:
            out.car["disposition_codes"] = [code]
            out.cells["disposition_codes"] = s.cell_name("E24")
            if code in LEGACY_DISPOSITIONS:
                out.notes.append(
                    f"Disposition '{_plain(disposition)}' is an older-form value; kept as written"
                )
    s.legacy("Were there any equipment problems?", "E28")
    s.legacy("Has the equipment been defective in the past?", "E29")
    s.legacy("If yes, when?", "C30")
    s.flag("safety_hazard", "E31", "Does the problem present a safety hazard?")
    s.flag("environmental_hazard", "E32", "Does the problem present an environmental hazard?")
    s.legacy("Describe the equipment failure", "A35")
    s.text("nonconformity_description", "A41")
    s.text("true_root_cause", "A47")
    action = s.raw("A52")
    if action is not None:
        out.actions.append(
            {
                "action": _plain(action),
                "owner": None,
                "target_date": None,
                "status": None,
                "completed_on": None,
                "cells": [s.cell_name("A52")],
            }
        )
        out.notes.append(
            "The corrective action text is imported verbatim as one action; the older form "
            "records no owner, target date or status for it."
        )
    sops, forms = s.raw("D55"), s.raw("D56")
    revised = [
        f"SOPs: {_plain(sops)}" if sops else None,
        f"Forms: {_plain(forms)}" if forms else None,
    ]
    if any(revised):
        out.car["procedures_revised"] = "\n".join(r for r in revised if r)
        out.cells["procedures_revised"] = f"{s.cell_name('D55')},{s.cell_name('D56')}"
    s.text("work_order_number", "D57")
    s.legacy("Date work order was closed", "D58")
    s.legacy("Work order status", "D59")
    s.text("supporting_documents", "A61")
    s.text("effectiveness_evidence", "A66")
    s.date("review_date", "E69", "Date the preventive action was verified")
    s.flag("training_completed", "E70", "Has follow-up training been completed?")
    s.code("root_cause_code", "E71", "Root cause category", ROOT_CAUSE_CATEGORIES)
    for row, function in zip(
        range(75, 83),
        (
            "Quality",
            "Safety",
            "Environmental",
            "Department Supervisor",
            "Operations",
            "Maintenance",
            "Engineering",
            "Process Manager",
        ),
        strict=True,
    ):
        for column in "CDF":
            s.legacy(f"Signature — {function}", f"{column}{row}")
    out.car["status"] = None
    out.notes.append(
        "The older form records no CAR status or effectiveness result; both are left not recorded."
    )
    _why_why(book, out)


def extract(path: Path) -> Extracted:
    """Read one workbook (read-only)."""
    from openpyxl import load_workbook  # development dependency

    out = Extracted(source_file=path.name, sha256=_sha256(path), layout="unknown")
    book = load_workbook(path, read_only=False, data_only=True)
    try:
        if "CAR" not in book.sheetnames:
            out.skipped = "No CAR sheet"
            return out
        sheet = book["CAR"]
        if _plain(sheet["A4"].value or "").upper() == "CAR NUMBER":
            out.layout = "rev2"
            _rev2(book, out)
        elif _plain(sheet["A2"].value or "").upper() == "CAR#":
            out.layout = "legacy"
            _legacy_form(book, out)
        else:
            out.skipped = "Unrecognised CAR layout"
        pictures = book["Pictures"] if "Pictures" in book.sheetnames else None
        if pictures is not None and getattr(pictures, "_images", None):
            out.notes.append(
                f"The Pictures sheet holds {len(pictures._images)} image(s); "
                "they remain in the source workbook"
            )
    finally:
        book.close()
    if not out.skipped and "request_date" not in out.car:
        out.skipped = "No request date"
    return out
