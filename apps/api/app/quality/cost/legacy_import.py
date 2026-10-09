"""Import the monthly Cost of Quality workbook from a reviewed mapping file.

    python -m app.quality.cost.legacy_import check mapping.json   # validate, recalculate
    python -m app.quality.cost.legacy_import plan  mapping.json   # compare with stored data
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
- Each month's inputs are stored as a monthly fact (the production pounds and
  sales revenue are the denominators of cost per pound and percent of sales).
- Each month's reported cost lines become Quality Cost records, so the
  Register, COPQ and the COQ Matrix all show them: Scrap and Off-spec
  (Internal Failure, the pounds times the loss per pound as material cost) and
  one Customer Complaint record (External Failure) with the complaint lines as
  its cost components. A line not reported makes no record. Imported records
  are Confirmed and Closed (the month's reported total), dated the first of
  the month, with no area, product or owner; they can be completed later in
  the Register.
- Stored months or imported records that differ from the file block
  ``apply``; equal ones are left untouched, so re-running is idempotent.
  Imported records are found by their source key; only the fields the file
  sets are compared, so later edits to owner, notes or status do not block.
- Writes are audited (``quality.cost_monthly_fact`` and
  ``quality.cost_record``) under the actor ``legacy-import``. Running
  ``apply`` requires ``quality.cost.manage`` by policy; it is an operator
  command run on the server.
"""

import argparse
import calendar
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
from app.quality.cost import records
from app.quality.cost.calculations import total
from app.quality.cost.models import CostMonthlyFact, CostRecord
from app.quality.cost.repository import CostRepository
from app.quality.cost.service import MonthInputs, element_values, month_cost
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR
from app.safety.site_calendar import site_today

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
class RecordLine:
    """A Quality Cost record converted from one month's cost line."""

    source_key: str
    values: dict[str, Any]
    cells: tuple[str, ...]


# Fields of an imported record the file sets, compared on a re-run.
RECORD_FIELDS = (
    "record_date",
    "title",
    "coq_class",
    "category_code",
    "material_cost",
    "testing_cost",
    "freight_cost",
    "customer_cost",
    "other_cost",
)


def _money(value: Decimal | None) -> str:
    return "not reported" if value is None else f"${value:,.2f}"


def record_lines(mapping: CostMapping, entry: MonthEntry, today: dt.date) -> list[RecordLine]:
    """The month's reported cost lines as Quality Cost records."""
    month_name = f"{calendar.month_name[entry.month]} {entry.year}"
    first = dt.date(entry.year, entry.month, 1)
    last = dt.date(entry.year, entry.month, calendar.monthrange(entry.year, entry.month)[1])
    common = {
        "record_date": first,
        "area_id": None,
        "financial_status": "confirmed",
        "status": "closed",
        "date_closed": max(min(last, today), first),
        "source": "legacy_import",
    }
    inputs = {k: v for k, v in month_values(mapping, entry).items() if k != "source"}
    elements = element_values(MonthInputs(year=entry.year, month=entry.month, **inputs))
    lines: list[RecordLine] = []

    def key(line: str) -> str:
        return f"coq-workbook/{entry.year:04d}-{entry.month:02d}/{line}"

    for code, label, lbs, rate in (
        ("scrap", "Scrap", entry.scrap_produced_lbs, entry.scrap_loss_per_lb),
        ("offspec", "Off-spec", entry.offspec_produced_lbs, entry.offspec_loss_per_lb),
    ):
        cost = elements[code]
        if cost is None:
            continue
        lines.append(
            RecordLine(
                source_key=key(code),
                values={
                    **common,
                    "title": f"{label} loss — {month_name} (monthly total)",
                    "coq_class": "internal_failure",
                    "category_code": f"internal_failure.{code}",
                    "description": (
                        f"Monthly {label.lower()} loss reported in {mapping.source}: "
                        f"{lbs.value:,} lb at ${rate.value} per lb."
                    ),
                    "material_cost": cost,
                },
                cells=(lbs.source_cell, rate.source_cell),
            )
        )

    complaint = {
        name: getattr(entry, name).value
        for name in (
            "outbound_freight",
            "return_freight",
            "warehousing_handling",
            "lab_investigation",
            "customer_credit_penalty",
            "complaint_rework_cost",
        )
    }
    if any(v is not None for v in complaint.values()):
        count = entry.complaint_count.value
        returned = entry.returned_product_lbs.value
        lines.append(
            RecordLine(
                source_key=key("customer-complaints"),
                values={
                    **common,
                    "title": f"Customer complaints — {month_name} (monthly total)",
                    "coq_class": "external_failure",
                    "category_code": "external_failure.customer_complaint",
                    "description": (
                        f"Monthly customer complaint cost reported in {mapping.source}. "
                        f"Complaints: {'not reported' if count is None else count}; "
                        f"returned product: "
                        f"{'not reported' if returned is None else f'{returned:,} lb'}. "
                        f"Outbound freight {_money(complaint['outbound_freight'])} and return "
                        f"freight {_money(complaint['return_freight'])} (freight); "
                        f"lab / investigation {_money(complaint['lab_investigation'])} "
                        f"(testing / lab); customer credit / penalty "
                        f"{_money(complaint['customer_credit_penalty'])} (customer); "
                        f"warehousing / handling {_money(complaint['warehousing_handling'])} and "
                        f"rework {_money(complaint['complaint_rework_cost'])} (other)."
                    ),
                    "freight_cost": total(
                        (complaint["outbound_freight"], complaint["return_freight"])
                    ),
                    "testing_cost": complaint["lab_investigation"],
                    "customer_cost": complaint["customer_credit_penalty"],
                    "other_cost": total(
                        (complaint["warehousing_handling"], complaint["complaint_rework_cost"])
                    ),
                },
                cells=tuple(
                    getattr(entry, name).source_cell
                    for name in (*complaint, "complaint_count", "returned_product_lbs")
                ),
            )
        )
    return lines


@dataclass(frozen=True)
class CostImportPlan:
    inserts: list[MonthEntry]
    unchanged: list[tuple[int, int]]
    # (year, month, field, stored, file)
    differing: list[tuple[int, int, str, Any, Any]]
    record_inserts: list[RecordLine]
    records_unchanged: list[str]
    # (source key, field, stored, file)
    records_differing: list[tuple[str, str, Any, Any]]

    @property
    def blocked(self) -> bool:
        return bool(self.differing or self.records_differing)

    @property
    def empty(self) -> bool:
        return not (self.inserts or self.record_inserts)


def _comparable(value: Any) -> Any:
    return Decimal(value).normalize() if isinstance(value, Decimal) else value


def plan_import(
    stored: dict[tuple[int, int], CostMonthlyFact],
    mapping: CostMapping,
    imported: dict[str, CostRecord] | None = None,
    *,
    today: dt.date,
) -> CostImportPlan:
    inserts: list[MonthEntry] = []
    unchanged: list[tuple[int, int]] = []
    differing: list[tuple[int, int, str, Any, Any]] = []
    record_inserts: list[RecordLine] = []
    records_unchanged: list[str] = []
    records_differing: list[tuple[str, str, Any, Any]] = []
    imported = imported or {}
    for entry in mapping.months:
        current = stored.get((entry.year, entry.month))
        if current is None:
            inserts.append(entry)
        else:
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
        for line in record_lines(mapping, entry, today):
            record = imported.get(line.source_key)
            if record is None:
                record_inserts.append(line)
                continue
            record_diffs = [
                (line.source_key, field, getattr(record, field), line.values.get(field))
                for field in RECORD_FIELDS
                if _comparable(getattr(record, field)) != _comparable(line.values.get(field))
            ]
            if record_diffs:
                records_differing.extend(record_diffs)
            else:
                records_unchanged.append(line.source_key)
    return CostImportPlan(
        inserts=inserts,
        unchanged=unchanged,
        differing=differing,
        record_inserts=record_inserts,
        records_unchanged=records_unchanged,
        records_differing=records_differing,
    )


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
) -> tuple[int, int, uuid.UUID | None]:
    """Insert the planned months and records in one audited transaction.
    Re-plans under the lock. Returns the number of months and records written."""
    change_set = uuid.uuid4()
    today = site_today(now)
    try:
        repository.lock()
        plan = plan_import(repository.facts(), mapping, repository.by_source_key(), today=today)
        if plan.blocked:
            raise RuntimeError("stored data differs from the file")
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
        if changes:
            repository.record_audit(
                actor_id=actor_id, change_set_id=change_set, at=now, changes=changes
            )
        actor = records.Actor(actor_id, now)
        for line in plan.record_inserts:
            reference = f"{path.name}: {','.join(line.cells)}"
            records.insert_audited(
                repository,
                {**line.values, "source_key": line.source_key, "source_reference": reference},
                (),
                actor,
                change_set,
            )
        if plan.empty:
            repository.rollback()
            return 0, 0, None
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    return len(changes), len(plan.record_inserts), change_set


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
    for key, field, current, new in plan.records_differing:
        print(f"DIFFERS record {key} {field}: stored {current}, file {new}")
    print(
        f"Months to insert: {[f'{e.year}-{e.month:02d}' for e in plan.inserts]}  "
        f"Already stored: {[f'{y}-{m:02d}' for y, m in plan.unchanged]}  "
        f"Differing: {len({(d[0], d[1]) for d in plan.differing})}"
    )
    for line in plan.record_inserts:
        print(
            f"Record to insert: {line.source_key}  {line.values['title']}  "
            f"total {total(line.values.get(f) for f in RECORD_FIELDS[4:])}"
        )
    print(
        f"Records to insert: {len(plan.record_inserts)}  "
        f"Already stored: {len(plan.records_unchanged)}  "
        f"Differing: {len({d[0] for d in plan.records_differing})}"
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

    now = dt.datetime.now(dt.UTC)
    with get_sessionmaker()() as session:
        repository = CostRepository(session)
        plan = plan_import(
            repository.facts(), mapping, repository.by_source_key(), today=site_today(now)
        )
        _print_plan(plan)
        blocked = mismatch or plan.blocked
        if command == "plan":
            return 1 if blocked else 0
        if blocked:
            print("Not applied: resolve the issues above first.", file=sys.stderr)
            return 1
        if plan.empty:
            print("Nothing to apply.")
            return 0
        months, record_count, change_set = apply_plan(
            repository, mapping, path, actor_id=LEGACY_IMPORT_ACTOR, now=now
        )
        print(f"Applied {months} months and {record_count} records (change set {change_set}).")
    return 0


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.quality.cost.legacy_import")
    parser.add_argument("command", choices=["check", "plan", "apply"])
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    return run(args.command, args.mapping)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
