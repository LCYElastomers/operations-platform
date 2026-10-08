"""Import TRIR Experience history from a reviewed mapping file.

    python -m app.safety.trir.legacy_import check mapping.json   # validate, recalculate
    python -m app.safety.trir.legacy_import plan  mapping.json   # compare with stored history
    python -m app.safety.trir.legacy_import apply mapping.json   # write (audited)

Rules:

- One entry per year: annual recordables, Incident count, annual man-hours,
  industry benchmark, and the legacy displayed TRIR and TIR, each with the
  source cell it came from. ``null`` is blank in the source and stored as
  unknown, never as 0.
- ``check`` recalculates TRIR (recordables × 200,000 ÷ man-hours) and TIR
  (Incident × 200,000 ÷ man-hours) and compares them with the legacy figures
  within the display tolerance; a mismatch blocks ``apply``.
- Stored years that differ from the file block ``apply``; equal years are left
  untouched, so re-running is idempotent.
- Monthly hours are never imported: they belong to Safety Performance.
- Writes are audited as ``safety.trir_annual_fact`` under the actor
  ``legacy-import``. Running ``apply`` requires ``safety.trir.manage`` by
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
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR
from app.safety.rates import COMPARISON_TOLERANCE, display_rate, incidence_rate
from app.safety.schemas import ReportingYear
from app.safety.trir.models import TrirAnnualFact
from app.safety.trir.repository import TrirRepository

ENTITY_TYPE = "safety.trir_annual_fact"
Label = Annotated[str, Field(min_length=1, max_length=1000)]
Cell = Annotated[str, Field(pattern=r"^[A-Z]{1,3}[0-9]{1,5}$")]
FIELDS = (
    "recordable_count",
    "incident_count",
    "annual_man_hours",
    "industry_benchmark",
    "benchmark_source",
    "legacy_displayed_trir",
    "legacy_tir",
    "source",
    "note",
)


class CountCell(CamelModel):
    model_config = ConfigDict(extra="forbid")

    value: Annotated[int, Field(ge=0)] | None
    source_cell: Cell


class DecimalCell(CamelModel):
    model_config = ConfigDict(extra="forbid")

    value: Annotated[Decimal, Field(ge=0)] | None
    source_cell: Cell


class YearEntry(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: ReportingYear
    recordable_count: CountCell
    incident_count: CountCell
    annual_man_hours: DecimalCell
    industry_benchmark: DecimalCell
    legacy_displayed_trir: DecimalCell
    legacy_tir: DecimalCell
    note: Label | None = None

    @model_validator(mode="after")
    def _hours_positive(self) -> Self:
        hours = self.annual_man_hours.value
        if hours is not None and hours <= 0:
            raise ValueError("annual man-hours must be above zero")
        return self


class TrirMapping(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    benchmark_source: Label
    notes: list[Label] = []
    years: Annotated[list[YearEntry], Field(min_length=1)]

    @model_validator(mode="after")
    def _years_are_unique(self) -> Self:
        years = [entry.year for entry in self.years]
        if len(years) != len(set(years)):
            raise ValueError("each year may appear only once")
        return self


def load_mapping(path: Path) -> TrirMapping:
    return TrirMapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _hours(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


def year_values(mapping: TrirMapping, entry: YearEntry) -> dict[str, Any]:
    return {
        "recordable_count": entry.recordable_count.value,
        "incident_count": entry.incident_count.value,
        "annual_man_hours": _hours(entry.annual_man_hours.value),
        "industry_benchmark": entry.industry_benchmark.value,
        "benchmark_source": mapping.benchmark_source,
        "legacy_displayed_trir": entry.legacy_displayed_trir.value,
        "legacy_tir": entry.legacy_tir.value,
        "source": mapping.source,
        "note": entry.note,
    }


def source_reference(path: Path, entry: YearEntry) -> str:
    cells = ",".join(
        cell.source_cell
        for cell in (
            entry.recordable_count,
            entry.incident_count,
            entry.annual_man_hours,
            entry.industry_benchmark,
            entry.legacy_displayed_trir,
            entry.legacy_tir,
        )
    )
    return f"{path.name}: {cells}"


@dataclass(frozen=True)
class Recalculation:
    year: int
    calculated_trir: Decimal | None
    legacy_trir: Decimal | None
    calculated_tir: Decimal | None
    legacy_tir: Decimal | None

    @property
    def trir_mismatch(self) -> bool:
        return _differs(self.calculated_trir, self.legacy_trir)

    @property
    def tir_mismatch(self) -> bool:
        return _differs(self.calculated_tir, self.legacy_tir)


def _differs(calculated: Decimal | None, legacy: Decimal | None) -> bool:
    if legacy is None:
        return False
    return calculated is None or abs(calculated - legacy) >= COMPARISON_TOLERANCE


def recalculate(entry: YearEntry) -> Recalculation:
    hours = entry.annual_man_hours.value
    return Recalculation(
        year=entry.year,
        calculated_trir=incidence_rate(entry.recordable_count.value, hours),
        legacy_trir=entry.legacy_displayed_trir.value,
        calculated_tir=incidence_rate(entry.incident_count.value, hours),
        legacy_tir=entry.legacy_tir.value,
    )


@dataclass(frozen=True)
class TrirImportPlan:
    inserts: list[YearEntry]
    unchanged: list[int]
    # (year, field, stored, file)
    differing: list[tuple[int, str, Any, Any]]


def _comparable(value: Any) -> Any:
    return Decimal(value).normalize() if isinstance(value, Decimal) else value


def plan_import(stored: dict[int, TrirAnnualFact], mapping: TrirMapping) -> TrirImportPlan:
    inserts: list[YearEntry] = []
    unchanged: list[int] = []
    differing: list[tuple[int, str, Any, Any]] = []
    for entry in mapping.years:
        current = stored.get(entry.year)
        if current is None:
            inserts.append(entry)
            continue
        values = year_values(mapping, entry)
        diffs = [
            (entry.year, field, getattr(current, field), values[field])
            for field in FIELDS
            if _comparable(getattr(current, field)) != _comparable(values[field])
        ]
        if diffs:
            differing.extend(diffs)
        else:
            unchanged.append(entry.year)
    return TrirImportPlan(inserts=inserts, unchanged=unchanged, differing=differing)


def audit_value(values: dict[str, Any], reference: str | None) -> dict[str, Any]:
    return {
        **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in values.items()},
        "source_reference": reference,
    }


def apply_plan(
    repository: TrirRepository,
    mapping: TrirMapping,
    path: Path,
    *,
    actor_id: str,
    now: dt.datetime,
) -> tuple[int, uuid.UUID | None]:
    """Insert the planned years in one audited transaction. Re-plans under the lock."""
    change_set = uuid.uuid4()
    try:
        repository.lock()
        plan = plan_import(repository.facts(), mapping)
        if plan.differing:
            raise RuntimeError("stored history differs from the file")
        changes = []
        for entry in plan.inserts:
            values = year_values(mapping, entry)
            reference = source_reference(path, entry)
            repository.insert(
                entry.year,
                {**values, "source_reference": reference},
                actor_id=actor_id,
                at=now,
            )
            changes.append(
                AuditChange(
                    action="create",
                    entity_type=ENTITY_TYPE,
                    entity_key=f"trir-annual-facts/{entry.year:04d}",
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


def _print_check(mapping: TrirMapping) -> bool:
    """Prints the file and the recalculation; True when a legacy figure disagrees."""
    print(f"Source: {mapping.source}")
    print(f"Benchmark: {mapping.benchmark_source}")
    for note in mapping.notes:
        print(f"Note: {note}")
    mismatch = False
    for entry in mapping.years:
        result = recalculate(entry)

        def shown(value: Decimal | int | None) -> str:
            return "blank" if value is None else str(value)

        print(
            f"  {entry.year}: recordables {shown(entry.recordable_count.value)}, "
            f"incidents {shown(entry.incident_count.value)}, "
            f"man-hours {shown(entry.annual_man_hours.value)}, "
            f"benchmark {shown(entry.industry_benchmark.value)}"
        )
        print(
            f"        TRIR calculated {shown(result.calculated_trir)} "
            f"(display {display_rate(result.calculated_trir) or 'n/a'}), "
            f"legacy {shown(result.legacy_trir)}" + ("  MISMATCH" if result.trir_mismatch else "")
        )
        if result.legacy_tir is not None or result.calculated_tir is not None:
            print(
                f"        TIR (legacy measure) calculated {shown(result.calculated_tir)}, "
                f"legacy {shown(result.legacy_tir)}" + ("  MISMATCH" if result.tir_mismatch else "")
            )
        if entry.note:
            print(f"        Note: {entry.note}")
        mismatch = mismatch or result.trir_mismatch or result.tir_mismatch
    return mismatch


def _print_plan(plan: TrirImportPlan) -> None:
    for year, field, current, new in plan.differing:
        print(f"DIFFERS {year} {field}: stored {current}, file {new}")
    print(
        f"To insert: {[e.year for e in plan.inserts]}  Already stored: {plan.unchanged}  "
        f"Differing: {len({d[0] for d in plan.differing})}"
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
        repository = TrirRepository(session)
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
        print(f"Applied {count} years (change set {change_set}).")
    return 0


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.trir.legacy_import")
    parser.add_argument("command", choices=["check", "plan", "apply"])
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    return run(args.command, args.mapping)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
