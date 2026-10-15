"""Record detail rules: which detail a record may carry, and how it is stored and audited.

A detail depends on the record's Incident Classifications (its
``classification_category_id`` and any further classifications), matched by
stable code:

- LOPC detail needs Spill / Release (``spill_release``).
- Damage detail needs Property Damage or Equipment Damage / Failure; a damage
  kind of ``property_damage`` needs Property Damage, and ``equipment_damage`` or
  ``equipment_failure`` need Equipment Damage / Failure.
- PIT detail needs PIT Accident (``pit_accident``).
- Serious-risk detail is the record-level PSIF designation. PSIF is not an
  Incident Classification, so any record may carry it; severity and category
  are given only for a PSIF.

A detail is never removed because a classification was removed: the change is
refused until the detail is removed too.

Narrative fields (notes, descriptions, rationale) are audited as a length and
digest, so the audit trail shows that they changed without repeating them.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.safety.records.detail_models import (
    IncidentDamageDetails,
    IncidentLopcDetails,
    IncidentPitDetails,
    IncidentSeriousRiskDetails,
)
from app.safety.records.schemas import (
    DamageDetails,
    DamageDetailsOut,
    LopcDetails,
    LopcDetailsOut,
    PitDetails,
    PitDetailsOut,
    SeriousRiskDetails,
    SeriousRiskDetailsOut,
)

DETAIL_ENTITY_TYPE = "safety.incident_record_detail"
LOPC_CONTRIBUTING_FACTOR = "metric:lopc_contributing_factor"
SPILL_RELEASE = "spill_release"
PROPERTY_DAMAGE = "property_damage"
EQUIPMENT_DAMAGE_FAILURE = "equipment_damage_failure"
PIT_ACCIDENT = "pit_accident"
# Damage kind -> the classification it needs.
DAMAGE_KIND_CLASSIFICATION = {
    "property_damage": PROPERTY_DAMAGE,
    "equipment_damage": EQUIPMENT_DAMAGE_FAILURE,
    "equipment_failure": EQUIPMENT_DAMAGE_FAILURE,
}


@dataclass(frozen=True)
class DetailSpec:
    kind: str
    # Request/response field, e.g. "lopc_details" (lopcDetails on the wire).
    field: str
    label: str
    model: type
    schema: type[BaseModel]
    out: type[BaseModel]
    # column -> taxonomy
    coded: dict[str, str]
    narrative: tuple[str, ...]
    # Any of these classification codes qualifies the record; empty: any record.
    requires: tuple[str, ...]
    requirement: str

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self.schema.model_fields)

    @property
    def wire_field(self) -> str:
        head, *rest = self.field.split("_")
        return head + "".join(part.title() for part in rest)


LOPC = DetailSpec(
    kind="lopc",
    field="lopc_details",
    label="LOPC details",
    model=IncidentLopcDetails,
    schema=LopcDetails,
    out=LopcDetailsOut,
    coded={
        "quantity_unit_code": "quantity_unit",
        "failure_mechanism_code": "lopc_failure_mechanism",
        "contributing_factor_code": LOPC_CONTRIBUTING_FACTOR,
        "secondary_containment_status_code": "secondary_containment_status",
    },
    narrative=("notes",),
    requires=(SPILL_RELEASE,),
    requirement="the Spill / Release classification",
)
DAMAGE = DetailSpec(
    kind="damage",
    field="damage_details",
    label="Damage / failure details",
    model=IncidentDamageDetails,
    schema=DamageDetails,
    out=DamageDetailsOut,
    coded={"damage_kind_code": "damage_kind", "currency_code": "currency"},
    narrative=("damage_description", "operational_impact", "notes"),
    requires=(PROPERTY_DAMAGE, EQUIPMENT_DAMAGE_FAILURE),
    requirement="the Property Damage or Equipment Damage / Failure classification",
)
PIT = DetailSpec(
    kind="pit",
    field="pit_details",
    label="PIT details",
    model=IncidentPitDetails,
    schema=PitDetails,
    out=PitDetailsOut,
    coded={"ownership_type_code": "pit_ownership"},
    narrative=("notes",),
    requires=(PIT_ACCIDENT,),
    requirement="the PIT Accident classification",
)
SERIOUS_RISK = DetailSpec(
    kind="serious_risk",
    field="serious_risk_details",
    label="Serious-risk details",
    model=IncidentSeriousRiskDetails,
    schema=SeriousRiskDetails,
    out=SeriousRiskDetailsOut,
    coded={
        "potential_severity_code": "potential_severity",
        "serious_risk_category_code": "serious_risk_category",
    },
    narrative=("rationale",),
    requires=(),
    requirement="",
)
SPECS = (LOPC, DAMAGE, PIT, SERIOUS_RISK)
BY_KIND = {spec.kind: spec for spec in SPECS}
TAXONOMIES = sorted({taxonomy for spec in SPECS for taxonomy in spec.coded.values()})


class DetailRuleError(ValueError):
    def __init__(self, error: str, message: str, field: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.field = field


def detail_entity_key(record_id: int, kind: str) -> str:
    return f"incident-records/{record_id}/{kind}"


def normalized(spec: DetailSpec, detail: BaseModel) -> dict[str, Any]:
    """Stored values: text trimmed, blank text not recorded."""
    values: dict[str, Any] = {}
    for column in spec.columns:
        value = getattr(detail, column)
        if isinstance(value, str):
            value = value.strip() or None
        values[column] = value
    return values


def stored_values(spec: DetailSpec, row: Any) -> dict[str, Any]:
    return {column: getattr(row, column) for column in spec.columns}


def _field(spec: DetailSpec, column: str) -> str:
    head, *rest = column.split("_")
    return f"{spec.wire_field}.{head}{''.join(part.title() for part in rest)}"


def check_values(
    spec: DetailSpec,
    values: dict[str, Any],
    *,
    known_codes: dict[str, set[str]],
    active_codes: dict[str, set[str]],
    stored: dict[str, Any] | None,
) -> None:
    """Pairing and code rules. An inactive code stays valid only when unchanged."""
    if spec is LOPC and (values["estimated_quantity"] is None) != (
        values["quantity_unit_code"] is None
    ):
        missing = (
            "quantity_unit_code" if values["quantity_unit_code"] is None else ("estimated_quantity")
        )
        raise DetailRuleError(
            "quantity_without_unit",
            "Give the estimated quantity and its unit together.",
            _field(spec, missing),
        )
    if spec is DAMAGE and (values["estimated_cost"] is None) != (values["currency_code"] is None):
        missing = "currency_code" if values["currency_code"] is None else "estimated_cost"
        raise DetailRuleError(
            "cost_without_currency",
            "Give the estimated cost and its currency together.",
            _field(spec, missing),
        )
    if (
        spec is SERIOUS_RISK
        and not values["is_psif"]
        and (values["potential_severity_code"] or values["serious_risk_category_code"])
    ):
        raise DetailRuleError(
            "severity_without_psif",
            "Potential severity and serious-risk category are given only for a PSIF.",
            _field(spec, "is_psif"),
        )
    for column, taxonomy in spec.coded.items():
        code = values[column]
        if code is None:
            continue
        unchanged = stored is not None and stored.get(column) == code
        if code not in known_codes.get(taxonomy, set()) or not (
            unchanged or code in active_codes.get(taxonomy, set())
        ):
            raise DetailRuleError(
                "invalid_code", f"Choose a listed value ({code} is not one).", _field(spec, column)
            )


def requirement_problem(
    spec: DetailSpec, values: dict[str, Any], classification_codes: set[str]
) -> str | None:
    """Why a record with these classifications cannot carry the detail; None if it can."""
    if spec.requires and not classification_codes.intersection(spec.requires):
        return f"{spec.label} need {spec.requirement}."
    if spec is DAMAGE and values.get("damage_kind_code") is not None:
        needed = DAMAGE_KIND_CLASSIFICATION[values["damage_kind_code"]]
        if needed not in classification_codes:
            label = "Property Damage" if needed == PROPERTY_DAMAGE else "Equipment Damage / Failure"
            return (
                f"A damage kind of {values['damage_kind_code']} needs the {label} classification."
            )
    return None


def _digest(value: str) -> str:
    return (
        f"[text, {len(value)} characters, sha256 {hashlib.sha256(value.encode()).hexdigest()[:12]}]"
    )


def audit_value(spec: DetailSpec, values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    out: dict[str, Any] = {}
    for column, value in values.items():
        if isinstance(value, Decimal):
            value = format(value.normalize(), "f")
        elif column in spec.narrative and isinstance(value, str):
            value = _digest(value)
        out[column] = value
    return out


def same(spec: DetailSpec, left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return left is right
    return all(left[c] == right[c] for c in spec.columns)
