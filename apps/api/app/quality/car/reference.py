"""CAR controlled values: the one definition used by validation, the API and the UI.

The lists are those of the current form, ``QMS-006-1 Corrective Action Report``
Rev. 2 (its hidden ``Lists`` sheet and its check-box rows). Values that only
the older CAR form used are kept as *legacy* values: imported CARs show them as
written, but they are not offered for new entries.

Codes are stored; labels are shown. Changing a label changes no data.
"""

from typing import Literal

CAR_NUMBER_PREFIX = "Q"
# Q-2026-001: prefix, request year, sequence within the year.
CAR_NUMBER_PATTERN = "^[A-Z]{1,5}-[0-9]{4}-[0-9]{3,6}$"

SOURCES: dict[str, str] = {
    "internal_audit": "Internal Audit",
    "external_audit": "External Audit",
    "customer_complaint": "Customer Complaint",
    "supplier_issue": "Supplier Issue",
    "process_deviation": "Process Deviation",
    "inspection_test": "Inspection / Test",
    "safety_incident": "Safety Incident",
    "environmental_incident": "Environmental Incident",
    "management_review": "Management Review",
    "other": "Other",
}

DEPARTMENTS: dict[str, str] = {
    "quality": "Quality",
    "safety": "Safety",
    "environmental": "Environmental",
    "logistics": "Logistics",
    "operations": "Operations",
    "finishing": "Finishing",
    "warehouse": "Warehouse",
    "maintenance": "Maintenance",
    "engineering": "Engineering",
    "other": "Other",
}
# Older CAR form only.
LEGACY_DEPARTMENTS: dict[str, str] = {
    "ca_operation": "CA Operation",
    "fa_operation": "FA Operation",
}

ROOT_CAUSE_CATEGORIES: dict[str, str] = {
    "people": "People",
    "method": "Method",
    "machine": "Machine",
    "material": "Material",
    "measurement": "Measurement",
    "environment": "Environment",
    "management_system": "Management System",
    "other": "Other",
}

DISPOSITIONS: dict[str, str] = {
    "hold": "Hold",
    "rework": "Rework",
    "recycle": "Recycle",
    "dispose": "Dispose",
    "return": "Return",
    "not_applicable": "N/A",
    "other": "Other",
}
# Older CAR form only.
LEGACY_DISPOSITIONS: dict[str, str] = {
    "blended": "Blended",
    "placed_in_totes": "Placed in totes",
    "isolated_in_tank": "Isolated in storage tank",
}

ActionStatus = Literal["open", "in_progress", "complete", "on_hold"]
ACTION_STATUSES: dict[str, str] = {
    "open": "Open",
    "in_progress": "In Progress",
    "complete": "Complete",
    "on_hold": "On Hold",
}

EffectivenessResult = Literal["effective", "not_effective"]
EFFECTIVENESS_RESULTS: dict[str, str] = {
    "effective": "Effective",
    "not_effective": "Not Effective",
}

CarStatus = Literal["open", "closed"]
CAR_STATUSES: dict[str, str] = {"open": "Open", "closed": "Closed"}
# Shown for imported CARs whose form records no status (the older form has none).
STATUS_NOT_RECORDED = "Not recorded"

# The approval rows of section 8, in form order.
APPROVAL_FUNCTIONS: dict[str, str] = {
    "quality": "Quality",
    "department_supervisor": "Department Supervisor",
    "safety_environmental": "Safety / Environmental",
    "operations_maintenance": "Operations / Maintenance",
    "engineering": "Engineering",
    "process_manager": "Process Manager",
}

# Related records. The Quality Cost link has its own column (one record per CAR).
REFERENCE_TYPES: dict[str, str] = {
    "car": "Corrective Action Report",
    "work_order": "Work order",
    "document": "Document / record",
    "evidence": "Evidence / photo",
    "moc": "MOC",
    "lot": "Lot",
    "complaint": "Customer complaint",
}

# The form's sections, which are also the steps of the entry workflow.
STEPS: tuple[tuple[str, str], ...] = (
    ("identify", "Identify"),
    ("contain", "Contain"),
    ("investigate", "Investigate"),
    ("evaluate", "Evaluate"),
    ("correct", "Correct"),
    ("verify", "Verify"),
    ("cost", "Cost"),
    ("close", "Close"),
)

# Optional production references, in form order.
PRODUCTION_FIELDS = ("product", "campaign", "lot", "location", "counterparty")
# The Why-Why worksheet's material / delivery block, in form order.
WHY_HEADER_TEXT_FIELDS = (
    "complaint_number",
    "dr_number",
    "material_name",
    "po_number",
    "supplier",
    "production_lot",
    "quantity_affected",
)
WHY_HEADER_DATE_FIELDS = ("date_reported", "date_delivered")
COST_FIELDS: tuple[tuple[str, str], ...] = (
    ("material_loss", "Material loss"),
    ("production_time_loss", "Production time loss"),
    ("other_costs", "Other costs"),
)


def department_label(code: str | None) -> str | None:
    if code is None:
        return None
    return DEPARTMENTS.get(code) or LEGACY_DEPARTMENTS.get(code) or code


def disposition_label(code: str) -> str:
    return DISPOSITIONS.get(code) or LEGACY_DISPOSITIONS.get(code) or code
