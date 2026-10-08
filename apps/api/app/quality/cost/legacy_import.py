"""Import monthly Cost of Quality inputs from a reviewed mapping file.

    python -m app.quality.cost.legacy_import check mapping.json   # validate, recalculate
    python -m app.quality.cost.legacy_import plan  mapping.json   # compare with stored months
    python -m app.quality.cost.legacy_import apply mapping.json   # write (audited)

Rules:

- One entry per reporting month with the workbook's input values (production,
  scrap and off-spec pounds and loss rates, complaint cost lines, sales
  revenue), each with the source cell it came from. ``null`` is blank in the
  source and stored as not reported, never as 0. Months with no figures are
  left out of the file, not stored as empty rows.
- ``check`` recalculates production quality cost (internal failure) and
  customer complaint cost (external failure) and compares them with the
  workbook's totals within one cent; a mismatch blocks ``apply``. The workbook
  totals are only checked, never stored.
- Stored months that differ from the file block ``apply``; equal months are
  left untouched, so re-running is idempotent.
- Writes are audited as ``quality.cost_monthly_fact`` under the actor
  ``legacy-import``. Running ``apply`` requires ``quality.cost.manage`` by
  policy; it is an operator command run on the server.
"""

import argparse
import datetime as dt
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from app.audit.recorder import AuditChange
from app.core.schemas import CamelModel
from app.db.session import get_sessionmaker
from app.quality.cost.models import CostMonthlyFact
from app.quality.cost.repository import CostRepository
from app.quality.cost.service import MonthInputs, month_cost
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR

ENTITY_TYPE = "quality.cost_monthly_fact"
TOLERANCE = Decimal("0.01")
Label = Annotated[str, Field(min_length=1, max_length=1000)]
Cell = Annotated[str, Field(pattern=r"^[A-Za-z_ ]{1,40}![A-Z]{1,3}[0-9]{1,5}$")]
DECIMAL_FIELDS = (
    "total_production_lbs",
    "scrap_produced_lbs",
    "offspec_produced_lbs",
    "scrap_loss_per_lb",
    "offspec_loss_per_lb",
    "returned_product_lbs",
    "outbound_freight",
    "return_freight",
    "warehousing_handling",
    "lab_investigation",
    "customer_credit_penalty",
    "complaint_rework_cost",
    "sales_revenue",
)
FIELDS = (*DECIMAL_FIELDS, "complaint_count", "source", "note")


class CountCell(CamelModel):
    model_config = ConfigDict(extra="forbid")

    value: Annotated[int, Field(ge=0)] | None
    source_cell: Cell


class DecimalCell(CamelModel):
    model_config = ConfigDict(extra="forbid")

    value: Annotated[Decimal, Field(ge=0)] | None
    source_cell: Cell


class MonthEntry(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: Annotated[int, Field(ge=2000, le=2100)]
    month: Annotated[int, Field(ge=1, le=12)]
    total_production_lbs: DecimalCell
    scrap_produced_lbs: DecimalCell
    offspec_produced_lbs: DecimalCell
    scrap_loss_per_lb: DecimalCell
    offspec_loss_per_lb: DecimalCell
    complaint_count: CountCell
    returned_product_lbs: DecimalCell
    outbound_freight: DecimalCell
    return_freight: DecimalCell
    warehousing_handling: DecimalCell
    lab_investigation: DecimalCell
    customer_credit_penalty: DecimalCell
    complaint_rework_cost: DecimalCell
    sales_revenue: DecimalCell
    # The workbook's own totals, checked against the recalculation; not stored.
    legacy_production_quality_cost: DecimalCell
    legacy_customer_complaint_cost: DecimalCell
    note: Label | None = None

    @model_validator(mode="after")
    def _has_figures(self) -> Self:
        if all(getattr(self, f).value is None for f in (*DECIMAL_FIELDS, "complaint_count")):
            raise ValueError(f"{self.year}-{self.month:02d} has no figures; leave it out")
        return self

    def cells(self) -> list[DecimalCell | CountCell]:
        return [getattr(self, f) for f in (*DECIMAL_FIELDS, "complaint_count")]


class CostMapping(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    notes: list[Label] = []
    months: Annotated[list[MonthEntry], Field(min_length=1)]

    @model_validator(mode="after")
    def _months_are_unique(self) -> Self:
        keys = [(entry.year, entry.month) for entry in self.months]
        if len(keys) != len(set(keys)):
            raise ValueError("each month may appear only once")
        return self


def load_mapping(path: Path) -> CostMapping:
    return CostMapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


def month_values(mapping: CostMapping, entry: MonthEntry) -> dict[str, Any]:
    return {
        **{f: getattr(entry, f).value for f in DECIMAL_FIELDS},
        "complaint_count": entry.complaint_count.value,
        "source": mapping.source,
        "note": entry.note,
    }


def source_reference(path: Path, entry: MonthEntry) -> str:
    return f"{path.name}: {','.join(cell.source_cell for cell in entry.cells())}"


@dataclass(frozen=True)
class Recalculation:
    year: int
    month: int
    internal_failure: Decimal | None
    legacy_internal: Decimal | None
    external_failure: Decimal | None
    legacy_external: Decimal | None

    @property
    def internal_mismatch(self) -> bool:
        return _differs(self.internal_failure, self.legacy_internal)

    @property
    def external_mismatch(self) -> bool:
        return _differs(self.external_failure, self.legacy_external)


def _differs(calculated: Decimal | None, legacy: Decimal | None) -> bool:
    if legacy is None:
        return False
    # The workbook shows a blank line as 0.
    return abs((calculated or Decimal(0)) - legacy) >= TOLERANCE


def recalculate(mapping: CostMapping, entry: MonthEntry) -> Recalculation:
    inputs = {k: v for k, v in month_values(mapping, entry).items() if k != "source"}
    cost = month_cost(MonthInputs(year=entry.year, month=entry.month, **inputs))
    return Recalculation(
        year=entry.year,
        month=entry.month,
        internal_failure=cost.internal_failure,
        legacy_internal=entry.legacy_production_quality_cost.value,
        external_failure=cost.external_failure,
        legacy_external=entry.legacy_customer_complaint_cost.value,
    )


@dataclass(frozen=True)
class CostImportPlan:
    inserts: list[MonthEntry]
    unchanged: list[tuple[int, int]]
    # (year, month, field, stored, file)
    differing: list[tuple[int, int, str, Any, Any]]


def _comparable(value: Any) -> Any:
    return Decimal(value).normalize() if isinstance(value, Decimal) else value


def plan_import(
    stored: dict[tuple[int, int], CostMonthlyFact], mapping: CostMapping
) -> CostImportPlan:
    inserts: list[MonthEntry] = []
    unchanged: list[tuple[int, int]] = []
    differing: list[tuple[int, int, str, Any, Any]] = []
    for entry in mapping.months:
        current = stored.get((entry.year, entry.month))
        if current is None:
            inserts.append(entry)
            continue
        values = month_values(mapping, entry)
        diffs = [
            (entry.year, entry.month, field, getattr(current, field), values[field])
            for field in FIELDS
            if _comparable(getattr(current, field)) != _comparable(values[field])
        ]
        if diffs:
            differing.extend(diffs)
        else:
            unchanged.append((entry.year, entry.month))
    return CostImportPlan(inserts=inserts, unchanged=unchanged, differing=differing)


def audit_value(values: dict[str, Any], reference: str | None) -> dict[str, Any]:
    return {
        **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in values.items()},
        "source_reference": reference,
    }


def apply_plan(
    repository: CostRepository,
    mapping: CostMapping,
    path: Path,
    *,
    actor_id: str,
    now: dt.datetime,
) -> tuple[int, uuid.UUID | None]:
    """Insert the planned months in one audited transaction. Re-plans under the lock."""
    change_set = uuid.uuid4()
    try:
        repository.lock()
        plan = plan_import(repository.facts(), mapping)
        if plan.differing:
            raise RuntimeError("stored months differ from the file")
        changes = []
        for entry in plan.inserts:
            values = month_values(mapping, entry)
            reference = source_reference(path, entry)
            repository.insert(
                entry.year,
                entry.month,
                {**values, "source_reference": reference},
                actor_id=actor_id,
                at=now,
            )
            changes.append(
                AuditChange(
                    action="create",
                    entity_type=ENTITY_TYPE,
                    entity_key=f"cost-monthly-facts/{entry.year:04d}-{entry.month:02d}",
                    old_value=None,
                    new_value=audit_value(values, reference),
                )
            )
        if not changes:
            repository.rollback()
            return 0, None
        repository.record_audit(
            actor_id=actor_id, change_set_id=change_set, at=now, changes=changes
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    return len(changes), change_set


def _shown(value: Decimal | int | None, unit: str = "") -> str:
    return "blank" if value is None else f"{value}{unit}"


def _print_check(mapping: CostMapping) -> bool:
    """Prints the file and the recalculation; True when a workbook total disagrees."""
    print(f"Source: {mapping.source}")
    for note in mapping.notes:
        print(f"Note: {note}")
    mismatch = False
    for entry in mapping.months:
        result = recalculate(mapping, entry)
        print(
            f"  {entry.year}-{entry.month:02d}: "
            f"production {_shown(entry.total_production_lbs.value, ' lb')}, "
            f"scrap {_shown(entry.scrap_produced_lbs.value, ' lb')}, "
            f"off-spec {_shown(entry.offspec_produced_lbs.value, ' lb')}, "
            f"complaints {_shown(entry.complaint_count.value)}, "
            f"sales {_shown(entry.sales_revenue.value)}"
        )
        print(
            f"        Internal failure calculated {_shown(result.internal_failure)}, "
            f"workbook {_shown(result.legacy_internal)}"
            + ("  MISMATCH" if result.internal_mismatch else "")
        )
        print(
            f"        External failure calculated {_shown(result.external_failure)}, "
            f"workbook {_shown(result.legacy_external)}"
            + ("  MISMATCH" if result.external_mismatch else "")
        )
        if entry.note:
            print(f"        Note: {entry.note}")
        mismatch = mismatch or result.internal_mismatch or result.external_mismatch
    return mismatch


def _print_plan(plan: CostImportPlan) -> None:
    for year, month, field, current, new in plan.differing:
        print(f"DIFFERS {year}-{month:02d} {field}: stored {current}, file {new}")
    print(
        f"To insert: {[f'{e.year}-{e.month:02d}' for e in plan.inserts]}  "
        f"Already stored: {[f'{y}-{m:02d}' for y, m in plan.unchanged]}  "
        f"Differing: {len({(d[0], d[1]) for d in plan.differing})}"
    )


def run(command: str, path: Path) -> int:
    try:
        mapping = load_mapping(path)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Invalid mapping file: {error}", file=sys.stderr)
        return 2

    mismatch = _print_check(mapping)
    if command == "check":
        return 1 if mismatch else 0

    with get_sessionmaker()() as session:
        repository = CostRepository(session)
        plan = plan_import(repository.facts(), mapping)
        _print_plan(plan)
        blocked = bool(mismatch or plan.differing)
        if command == "plan":
            return 1 if blocked else 0
        if blocked:
            print("Not applied: resolve the issues above first.", file=sys.stderr)
            return 1
        if not plan.inserts:
            print("Nothing to apply.")
            return 0
        count, change_set = apply_plan(
            repository,
            mapping,
            path,
            actor_id=LEGACY_IMPORT_ACTOR,
            now=dt.datetime.now(dt.UTC),
        )
        print(f"Applied {count} months (change set {change_set}).")
    return 0


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.quality.cost.legacy_import")
    parser.add_argument("command", choices=["check", "plan", "apply"])
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    return run(args.command, args.mapping)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
