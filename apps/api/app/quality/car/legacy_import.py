"""Import historical CAR workbooks from a reviewed mapping file.

    # Development machine (needs openpyxl): read the workbooks, write the mapping
    # file and the migration report for review. Workbooks are opened read-only.
    python -m app.quality.car.legacy_import extract <workbook dir> mapping.json [--report report.md]

    # Server:
    python -m app.quality.car.legacy_import check mapping.json   # validate the file
    python -m app.quality.car.legacy_import plan  mapping.json   # compare with stored data
    python -m app.quality.car.legacy_import apply mapping.json   # write (audited)

Rules:

- One entry per CAR workbook, keyed ``car-workbook/<CAR number>``. The CAR
  number is the workbook's own; it is never renumbered. A number already used
  by a report that was not imported from that workbook blocks ``apply``.
- Values are those of the workbook as mapped by ``app.quality.car.workbook``:
  blank stays not recorded; older-form answers without a current field are kept
  verbatim as legacy fields; each entry records its source file and its SHA-256.
- A stored import that differs from the file blocks ``apply``; equal ones are
  left untouched, so re-running is idempotent. Later edits in the platform to
  fields the file leaves blank do not block.
- Writes are audited (``quality.car`` and ``quality.car_action``) under the
  actor ``legacy-import``. Running ``apply`` requires ``quality.cars.manage``
  by policy; it is an operator command run on the server.
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
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from app.core.schemas import CamelModel
from app.db.session import get_sessionmaker
from app.quality.car import service
from app.quality.car.models import Car
from app.quality.car.reference import (
    DEPARTMENTS,
    DISPOSITIONS,
    LEGACY_DEPARTMENTS,
    LEGACY_DISPOSITIONS,
    ROOT_CAUSE_CATEGORIES,
    SOURCES,
)
from app.quality.car.repository import Approval, CarRepository, WhyStep
from app.quality.car.schemas import ApprovalFunction, CarFields, LongText, ShortText
from app.quality.cost.records import Actor
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR

SOURCE_KEY_PREFIX = "car-workbook/"
Label = Annotated[str, Field(min_length=1, max_length=1000)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FileName = Annotated[str, Field(min_length=1, max_length=255)]


class _Input(CamelModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportedApproval(_Input):
    function_code: ApprovalFunction
    name: Annotated[str, Field(min_length=1, max_length=200)]
    approved_on: dt.date | None = None


class ImportedCar(CarFields):
    car_number: Annotated[str, Field(pattern=r"^[A-Z]{1,5}-[0-9]{4}-[0-9]{3,6}$")]
    # Older-form reports record no status.
    status: Literal["open", "closed"] | None = None
    # Names as written on the workbook; kept verbatim and not linked to users.
    reviewer: ShortText | None = None
    closure_approved_by: ShortText | None = None
    approvals: Annotated[list[ImportedApproval], Field(max_length=10)] = []


class ImportedAction(_Input):
    action: LongText
    owner: ShortText | None = None
    target_date: dt.date | None = None
    status: Literal["open", "in_progress", "complete", "on_hold"] | None = None
    completed_on: dt.date | None = None
    cells: list[Annotated[str, Field(max_length=60)]] = []


class LegacyField(_Input):
    label: Label
    value: Annotated[str, Field(min_length=1, max_length=8000)]


class CarEntry(_Input):
    source_file: FileName
    sha256: Sha256
    layout: Literal["rev2", "legacy"]
    car: ImportedCar
    actions: Annotated[list[ImportedAction], Field(max_length=20)] = []
    legacy_fields: Annotated[list[LegacyField], Field(max_length=100)] = []
    # Field -> source cell; kept in the stored source reference, never returned by the API.
    cells: dict[str, Annotated[str, Field(max_length=200)]] = {}
    warnings: list[Label] = []
    notes: list[Label] = []

    @property
    def source_key(self) -> str:
        return f"{SOURCE_KEY_PREFIX}{self.car.car_number}"


class SkippedFile(_Input):
    source_file: FileName
    sha256: Sha256
    reason: Label


class CarMapping(_Input):
    source: Label
    notes: list[Label] = []
    cars: list[CarEntry]
    skipped: list[SkippedFile] = []

    @model_validator(mode="after")
    def _numbers_are_unique(self) -> Self:
        numbers = [entry.car.car_number for entry in self.cars]
        if len(numbers) != len(set(numbers)):
            raise ValueError("each CAR number may appear only once")
        return self


def load_mapping(path: Path) -> CarMapping:
    return CarMapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


# Values ------------------------------------------------------------------------------


def _problems(entry: CarEntry) -> list[str]:
    """Controlled values outside the current and older-form lists."""
    car = entry.car
    problems = []
    for value, allowed, label in (
        (car.source_code, SOURCES, "source"),
        (car.department_code, {**DEPARTMENTS, **LEGACY_DEPARTMENTS}, "department"),
        (car.root_cause_code, ROOT_CAUSE_CATEGORIES, "root cause"),
    ):
        if value is not None and value not in allowed:
            problems.append(f"unknown {label} '{value}'")
    for code in car.disposition_codes:
        if code not in DISPOSITIONS and code not in LEGACY_DISPOSITIONS:
            problems.append(f"unknown disposition '{code}'")
    if car.status == "closed" and car.date_closed is None:
        problems.append("closed without a date closed")
    if car.due_date is not None and car.due_date < car.request_date:
        problems.append("due date before the request date")
    return problems


def migration_notes(mapping: CarMapping, entry: CarEntry) -> str:
    layout = "QMS-006-1 Rev. 2" if entry.layout == "rev2" else "the older CAR form"
    lines = [
        f"Imported from the workbook '{entry.source_file}' ({layout}), "
        f"SHA-256 {entry.sha256[:12]}…. The workbook remains the original record.",
        *entry.notes,
        *(f"Review: {w}" for w in entry.warnings),
    ]
    return "\n".join(lines)[:8000]


def car_values(mapping: CarMapping, entry: CarEntry) -> dict[str, Any]:
    car = entry.car
    values = {f: getattr(car, f) for f in service.EDITABLE_FIELDS}
    values.update(
        car_number=car.car_number,
        disposition_codes=list(car.disposition_codes),
        legacy_fields=[{"label": f.label, "value": f.value} for f in entry.legacy_fields] or None,
        migration_notes=migration_notes(mapping, entry),
        source="legacy_import",
        source_key=entry.source_key,
    )
    return values


def source_reference(entry: CarEntry) -> str:
    cells = ",".join(sorted(set(entry.cells.values())))
    return f"{entry.source_file} (sha256 {entry.sha256}): {cells}"[:4000]


def _why_steps(entry: CarEntry) -> tuple[WhyStep, ...]:
    return tuple(
        WhyStep(s.what, s.why, s.root_cause, s.countermeasure, s.who, s.target_date)
        for s in entry.car.why_steps
    )


def _approvals(entry: CarEntry) -> tuple[Approval, ...]:
    return tuple(Approval(a.function_code, a.name, a.approved_on) for a in entry.car.approvals)


# Plan ----------------------------------------------------------------------------------

# Compared on a re-run; the file's blanks do not block later edits.
COMPARED_FIELDS = (
    "car_number",
    "subject",
    "requested_by",
    "request_date",
    "assigned_to",
    "due_date",
    "nonconformity_description",
    "true_root_cause",
    "material_loss",
    "production_time_loss",
    "other_costs",
)


def _comparable(value: Any) -> Any:
    return value.normalize() if isinstance(value, Decimal) else value


@dataclass(frozen=True)
class CarImportPlan:
    inserts: list[CarEntry]
    unchanged: list[str]
    # (CAR number, field, stored, file)
    differing: list[tuple[str, str, Any, Any]]
    # CAR numbers used by reports not imported from the file's workbook.
    number_conflicts: list[str]
    # (CAR number, problem)
    invalid: list[tuple[str, str]]

    @property
    def blocked(self) -> bool:
        return bool(self.differing or self.number_conflicts or self.invalid)

    @property
    def empty(self) -> bool:
        return not self.inserts


def plan_import(mapping: CarMapping, imported: dict[str, Car], numbers: set[str]) -> CarImportPlan:
    inserts: list[CarEntry] = []
    unchanged: list[str] = []
    differing: list[tuple[str, str, Any, Any]] = []
    conflicts: list[str] = []
    invalid: list[tuple[str, str]] = []
    for entry in mapping.cars:
        number = entry.car.car_number
        invalid.extend((number, p) for p in _problems(entry))
        stored = imported.get(entry.source_key)
        if stored is None:
            if number in numbers:
                conflicts.append(number)
            else:
                inserts.append(entry)
            continue
        values = car_values(mapping, entry)
        diffs = [
            (number, f, getattr(stored, f), values[f])
            for f in COMPARED_FIELDS
            if values[f] is not None and _comparable(getattr(stored, f)) != _comparable(values[f])
        ]
        if diffs:
            differing.extend(diffs)
        else:
            unchanged.append(number)
    return CarImportPlan(inserts, unchanged, differing, conflicts, invalid)


def _existing(repository: CarRepository) -> tuple[dict[str, Car], set[str]]:
    return repository.by_source_key(), repository.all_numbers()


def apply_plan(
    repository: CarRepository, mapping: CarMapping, *, actor_id: str, now: dt.datetime
) -> tuple[int, int, uuid.UUID | None]:
    """Insert the planned reports and their actions in one audited transaction.
    Re-plans under the lock. Returns the number of reports and actions written."""
    change_set = uuid.uuid4()
    actor = Actor(actor_id, now)
    actions = 0
    try:
        repository.lock_import()
        repository.lock_numbers()
        plan = plan_import(mapping, *_existing(repository))
        if plan.blocked:
            raise RuntimeError("stored data differs from the file")
        if plan.empty:
            repository.rollback()
            return 0, 0, None
        for entry in plan.inserts:
            values = {**car_values(mapping, entry), "source_reference": source_reference(entry)}
            car_id = service.insert_audited(
                repository,
                values,
                _why_steps(entry),
                _approvals(entry),
                (),
                actor,
                change_set,
            )
            for action in entry.actions:
                service.insert_action_audited(
                    repository,
                    car_id,
                    {
                        "action": action.action,
                        "owner": action.owner,
                        "target_date": action.target_date,
                        "status": action.status,
                        "completed_on": action.completed_on,
                    },
                    actor,
                    change_set,
                )
                actions += 1
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    return len(plan.inserts), actions, change_set


# Output --------------------------------------------------------------------------------


def _print_check(mapping: CarMapping) -> bool:
    """Prints the file; True when an entry has a value outside the lists."""
    print(f"Source: {mapping.source}")
    for note in mapping.notes:
        print(f"Note: {note}")
    problem = False
    for entry in mapping.cars:
        car = entry.car
        print(
            f"  {car.car_number}  {entry.layout:<6}  requested {car.request_date}  "
            f"status {car.status or 'not recorded'}  actions {len(entry.actions)}  "
            f"legacy fields {len(entry.legacy_fields)}  ({entry.source_file})"
        )
        print(f"        {car.subject}")
        for warning in entry.warnings:
            print(f"        Warning: {warning}")
        for issue in _problems(entry):
            print(f"        INVALID: {issue}")
            problem = True
    for skipped in mapping.skipped:
        print(f"  skipped  {skipped.source_file}: {skipped.reason}")
    return problem


def _print_plan(plan: CarImportPlan) -> None:
    for number, field, current, new in plan.differing:
        print(f"DIFFERS {number} {field}: stored {current!r}, file {new!r}")
    for number in plan.number_conflicts:
        print(f"CONFLICT {number}: the number is used by a report not imported from this file")
    print(
        f"Reports to insert: {[e.car.car_number for e in plan.inserts]}  "
        f"Already stored: {plan.unchanged}  "
        f"Differing: {sorted({d[0] for d in plan.differing})}  "
        f"Number conflicts: {plan.number_conflicts}"
    )


def run(command: str, path: Path) -> int:
    try:
        mapping = load_mapping(path)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Invalid mapping file: {error}", file=sys.stderr)
        return 2
    problem = _print_check(mapping)
    if command == "check":
        return 1 if problem else 0

    now = dt.datetime.now(dt.UTC)
    with get_sessionmaker()() as session:
        repository = CarRepository(session)
        plan = plan_import(mapping, *_existing(repository))
        _print_plan(plan)
        blocked = problem or plan.blocked
        if command == "plan":
            return 1 if blocked else 0
        if blocked:
            print("Not applied: resolve the issues above first.", file=sys.stderr)
            return 1
        if plan.empty:
            print("Nothing to apply.")
            return 0
        cars, actions, change_set = apply_plan(
            repository, mapping, actor_id=LEGACY_IMPORT_ACTOR, now=now
        )
        print(f"Applied {cars} reports and {actions} actions (change set {change_set}).")
    return 0


# Extract (development machine) ---------------------------------------------------------


def _count_mapped(car: dict[str, Any], actions: list[Any]) -> int:
    mapped = sum(1 for k, v in car.items() if v not in (None, [], "") and k != "status")
    if car.get("status") is not None:
        mapped += 1
    return mapped + len(actions)


def number_gaps(numbers: list[str]) -> list[str]:
    """Sequence numbers missing below the highest of each prefix and year."""
    by_year: dict[tuple[str, int], set[int]] = {}
    for number in numbers:
        parsed = service.parse_number(number)
        if parsed is not None:
            by_year.setdefault((parsed[0], parsed[1]), set()).add(parsed[2])
    return [
        f"{prefix}-{year}-{n:03d}"
        for (prefix, year), used in sorted(by_year.items())
        for n in range(1, max(used) + 1)
        if n not in used
    ]


def report_markdown(mapping: CarMapping, extracted: list[Any]) -> str:
    lines = [
        "# CAR workbook migration report",
        "",
        f"Source: {mapping.source}",
        "",
        "Generated by `python -m app.quality.car.legacy_import extract`. The workbooks were "
        "opened read-only; none was modified, moved or renamed.",
        "",
        "| Source File | CAR Number | Result | Fields Mapped | Fields Unmapped | Warnings |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in extracted:
        if item.skipped:
            lines.append(f"| {item.source_file} | — | Skipped: {item.skipped} | 0 | 0 | — |")
            continue
        unmapped = "; ".join(f"{f['label']}" for f in item.legacy_fields) or "—"
        warnings = "; ".join(item.warnings) or "—"
        result = "Ready to import" + (" (older form)" if item.layout == "legacy" else " (Rev. 2)")
        lines.append(
            f"| {item.source_file} | {item.car['car_number']} | {result} | "
            f"{_count_mapped(item.car, item.actions)} | {len(item.legacy_fields)}: {unmapped} | "
            f"{warnings} |"
        )
    gaps = number_gaps([entry.car.car_number for entry in mapping.cars])
    if gaps:
        lines += [
            "",
            "No workbook was found for: "
            + ", ".join(gaps)
            + ". These numbers are left unused; new CARs continue after the highest number.",
        ]
    lines += ["", "## Notes per CAR", ""]
    for item in extracted:
        if item.skipped:
            continue
        lines.append(f"### {item.car['car_number']} — {item.source_file}")
        lines.append("")
        for note in item.notes:
            lines.append(f"- {' '.join(note.split())}")
        for warning in item.warnings:
            lines.append(f"- Review: {' '.join(warning.split())}")
        for field in item.legacy_fields:
            value = " ".join(field["value"].split())
            lines.append(f"- Kept as a legacy field: **{field['label']}**: {value}")
        lines.append("")
    return "\n".join(lines)


def extract_directory(directory: Path) -> tuple[CarMapping, list[Any]]:
    from app.quality.car.workbook import extract

    extracted = [
        extract(path) for path in sorted(directory.glob("*.xlsx")) if not path.name.startswith("~$")
    ]
    cars = []
    skipped = []
    for item in extracted:
        if item.skipped:
            skipped.append(
                {"source_file": item.source_file, "sha256": item.sha256, "reason": item.skipped}
            )
            continue
        cars.append(
            {
                "source_file": item.source_file,
                "sha256": item.sha256,
                "layout": item.layout,
                "car": item.car,
                "actions": item.actions,
                "legacy_fields": item.legacy_fields,
                "cells": item.cells,
                "warnings": item.warnings,
                "notes": item.notes,
            }
        )
    mapping = CarMapping.model_validate(
        {
            "source": f"CAR workbooks in {directory.parent.name}/{directory.name}",
            "notes": [
                "Generated from the workbooks by app.quality.car.workbook; review before applying."
            ],
            "cars": sorted(cars, key=lambda c: c["car"]["car_number"]),
            "skipped": skipped,
        }
    )
    return mapping, extracted


def extract_command(directory: Path, output: Path, report: Path | None) -> int:
    mapping, extracted = extract_directory(directory)
    output.write_text(
        json.dumps(mapping.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(mapping.cars)} CARs to {output} ({len(mapping.skipped)} file(s) skipped).")
    if report is not None:
        report.write_text(report_markdown(mapping, extracted) + "\n", encoding="utf-8")
        print(f"Wrote the migration report to {report}.")
    return 0


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.quality.car.legacy_import")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("directory", type=Path)
    ex.add_argument("output", type=Path)
    ex.add_argument("--report", type=Path)
    for name in ("check", "plan", "apply"):
        sub.add_parser(name).add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    if args.command == "extract":
        return extract_command(args.directory, args.output, args.report)
    return run(args.command, args.mapping)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
