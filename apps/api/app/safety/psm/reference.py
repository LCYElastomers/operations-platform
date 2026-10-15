"""Controlled values of Process Safety Management.

Stored values are lower-case codes; the labels are what users see. These are
platform values, not workbook data. The workbook's own wording (for example a
risk cell reading "Medium ") is kept verbatim beside the code on imported rows.
"""

from typing import Final

DISPOSITIONS: Final = {
    "pending_review": "Pending Review",
    "accepted": "Accepted",
    "rejected": "Rejected",
}

ACTION_STATUSES: Final = {
    "not_started": "Not Started",
    "in_progress": "In Progress",
    "pending_verification": "Pending Verification",
    "closed": "Closed",
}
OPEN_ACTION_STATUSES: Final = ("not_started", "in_progress", "pending_verification")

# Highest first. A recommendation's governing risk is the highest of its scenarios'.
RISKS: Final = {"high": "High", "medium": "Medium", "low": "Low"}
RISK_RANK: Final = {"high": 3, "medium": 2, "low": 1}

EVIDENCE_TYPES: Final = {
    "engineering_calculation": "Engineering Calculation",
    "moc": "MOC",
    "work_order": "Work Order",
    "photo": "Photo",
    "pid": "P&ID",
    "procedure": "Procedure",
    "training_record": "Training Record",
    "inspection": "Inspection",
    "other": "Other",
}

STUDY_STATUSES: Final = {"active": "Active", "complete": "Complete", "archived": "Archived"}

UPDATE_TYPES: Final = {
    "comment": "Comment",
    "status_change": "Status change",
    "closure_request": "Closure requested",
    "closure_approved": "Closure approved",
    "closure_returned": "Returned to In Progress",
    "reopened": "Reopened",
    "assignment": "Assignment",
    "disposition": "Disposition",
}

NOTIFICATION_EVENTS: Final = {
    "action_assigned": "Action assigned",
    "owner_changed": "Owner changed",
    "due_date_changed": "Due date assigned or changed",
    "due_soon": "Action due soon",
    "overdue": "Action overdue",
    "status_changed": "Status changed",
    "comment_added": "Update added",
    "closure_requested": "Closure requested",
    "closure_approved": "Closure approved",
    "closure_returned": "Returned to In Progress",
    "reopened": "Action reopened",
}

NOTIFICATION_STATUSES: Final = {
    "queued": "Queued",
    "sent": "Sent",
    "failed": "Failed",
    "skipped": "Not sent",
}

# Ages of open actions, in days since the action was created (both ends inclusive).
AGING_BUCKETS: Final = (
    ("0_30", "0-30 days", 0, 30),
    ("31_60", "31-60 days", 31, 60),
    ("61_90", "61-90 days", 61, 90),
    ("90_plus", "90+ days", 91, None),
)

# Ordinary status moves an action manager may make. Closure goes only through a
# closure request and its verification; reopening only through the reopen workflow.
MANUAL_TRANSITIONS: Final = {("not_started", "in_progress"), ("in_progress", "not_started")}

MIN_REASON_LENGTH: Final = 10
MIN_REJECTION_LENGTH: Final = 20
MAX_SHORT: Final = 200
MAX_TEXT: Final = 8000

# Attachments are stored in PostgreSQL; this bounds each file.
MAX_ATTACHMENT_BYTES: Final = 10 * 1024 * 1024
ATTACHMENT_EXTENSIONS: Final = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".msg": "application/vnd.ms-outlook",
    ".eml": "message/rfc822",
    ".dwg": "application/acad",
    ".zip": "application/zip",
}

SYSTEM_IMPORT_ACTOR: Final = "legacy-import"


def display_id(prefix: str, number: int) -> str:
    """PHA-2026-001: the study's recommendation prefix and the zero-padded number."""
    return f"{prefix}-{number:03d}"


def action_number(year: int, sequence: int) -> str:
    return f"PSM-ACT-{year}-{sequence:03d}"
