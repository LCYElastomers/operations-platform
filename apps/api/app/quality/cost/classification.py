"""Cost of Quality classification: classes, categories, cost components, statuses.

The single reference for what a Quality Cost record can be. Categories belong
to one COQ class; add a category by adding it here (codes are stored on the
record, so a code must never be renamed or reused). Good COQ and Poor COQ
(COPQ) are derived from the class and never chosen by a user.
"""

from dataclasses import dataclass
from typing import Literal

CoqClass = Literal["prevention", "appraisal", "internal_failure", "external_failure"]
FinancialStatus = Literal["potential", "validating", "confirmed", "closed"]
OperationalStatus = Literal["open", "under_review", "action_required", "monitoring", "closed"]

COQ_CLASSES: dict[CoqClass, str] = {
    "prevention": "Prevention",
    "appraisal": "Appraisal",
    "internal_failure": "Internal Failure",
    "external_failure": "External Failure",
}
GOOD_CLASSES: frozenset[str] = frozenset({"prevention", "appraisal"})
POOR_CLASSES: frozenset[str] = frozenset({"internal_failure", "external_failure"})

FINANCIAL_STATUSES: dict[FinancialStatus, str] = {
    "potential": "Potential",
    "validating": "Validating",
    "confirmed": "Confirmed",
    "closed": "Closed",
}
# Confirmed figures are the official cost; the rest is potential exposure.
CONFIRMED_FINANCIAL: frozenset[str] = frozenset({"confirmed", "closed"})
POTENTIAL_FINANCIAL: frozenset[str] = frozenset({"potential", "validating"})

OPERATIONAL_STATUSES: dict[OperationalStatus, str] = {
    "open": "Open",
    "under_review": "Under Review",
    "action_required": "Action Required",
    "monitoring": "Monitoring",
    "closed": "Closed",
}

# Cost components in form order: (field, label).
COST_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("material_cost", "Material"),
    ("labor_cost", "Labor"),
    ("production_cost", "Production / downtime"),
    ("testing_cost", "Testing / lab"),
    ("maintenance_cost", "Maintenance"),
    ("freight_cost", "Freight"),
    ("disposal_cost", "Disposal"),
    ("customer_cost", "Customer"),
    ("other_cost", "Other"),
)
COMPONENT_FIELDS: tuple[str, ...] = tuple(field for field, _ in COST_COMPONENTS)

# What a record can reference. A related module adds its type here (for example
# a Corrective Action Report) so links can be made to its records.
REFERENCE_TYPES: dict[str, str] = {
    "reference": "Reference / document number",
    # Key: the CAR number (Q-2026-006).
    "car": "Corrective Action Report",
}


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    coq_class: CoqClass


def _categories(coq_class: CoqClass, *items: tuple[str, str]) -> tuple[Category, ...]:
    return tuple(Category(f"{coq_class}.{code}", label, coq_class) for code, label in items)


CATEGORIES: tuple[Category, ...] = (
    *_categories(
        "prevention",
        ("training", "Training"),
        ("quality_planning", "Quality Planning"),
        ("process_improvement", "Process Improvement"),
        ("preventive_maintenance", "Preventive Maintenance"),
        ("supplier_qualification", "Supplier Qualification"),
        ("error_proofing", "Error Proofing"),
        ("procedure_documentation", "Procedure / Documentation"),
        ("other", "Other"),
    ),
    *_categories(
        "appraisal",
        ("inspection", "Inspection"),
        ("laboratory_testing", "Laboratory Testing"),
        ("product_testing", "Product Testing"),
        ("incoming_inspection", "Incoming Inspection"),
        ("calibration", "Calibration"),
        ("audit", "Audit"),
        ("verification", "Verification"),
        ("other", "Other"),
    ),
    *_categories(
        "internal_failure",
        ("scrap", "Scrap"),
        # Off-spec product sold as C-grade, as reported in the COQ workbook.
        ("offspec", "Off-spec / Downgrade"),
        ("rework", "Rework"),
        ("sorting", "Sorting"),
        ("retesting", "Retesting"),
        ("downtime", "Downtime"),
        ("yield_loss", "Yield Loss"),
        ("material_loss", "Material Loss"),
        ("disposal", "Disposal"),
        ("process_failure", "Process Failure"),
        ("other", "Other"),
    ),
    *_categories(
        "external_failure",
        ("customer_complaint", "Customer Complaint"),
        ("return", "Return"),
        ("credit", "Credit"),
        ("replacement", "Replacement"),
        ("warranty", "Warranty"),
        ("customer_sorting", "Customer Sorting"),
        ("premium_freight", "Premium Freight"),
        ("customer_rework", "Customer Rework"),
        ("other", "Other"),
    ),
)
CATEGORY_BY_CODE: dict[str, Category] = {c.code: c for c in CATEGORIES}


def is_poor(coq_class: str) -> bool:
    """Internal and external failure costs are poor quality cost (COPQ)."""
    return coq_class in POOR_CLASSES


def quality_group(coq_class: str) -> Literal["good", "poor"]:
    return "poor" if is_poor(coq_class) else "good"


def category_label(code: str) -> str:
    category = CATEGORY_BY_CODE.get(code)
    return category.label if category else code
