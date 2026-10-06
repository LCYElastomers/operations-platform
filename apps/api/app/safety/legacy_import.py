"""Import historical Safety monthly values from a reviewed mapping file.

The 2026 LCY EHS workbook is the migration source. Its values are first
transcribed into a JSON mapping file, reviewed, and then loaded here. Start
from ``apps/api/import_templates/safety_incidents.template.json``. This module
is not used by the API.

    python -m app.safety.legacy_import check  mapping.json   # validate, no database
    python -m app.safety.legacy_import plan   mapping.json   # compare with stored values
    python -m app.safety.legacy_import apply  mapping.json   # write (audited)

Rules:

- The file mirrors the logical sections (Incident & Near Miss Totals, Incident
  Classification, LOPC, ...). Each category lists 12 months, January first.
- ``null`` means unreported in the source and is never written; ``0`` is a
  reported zero. Categories or sections left out of the file are not touched.
- Incident and Near Miss are explicit source metrics. Incident is never
  derived from Incident Classification, whose categories may overlap.
- ``expectedYtd`` records totals stated elsewhere in the workbook for one
  category. Any difference from the sum of its reported months is reported
  and blocks ``apply``. Discrepancies must be resolved in the mapping file
  (and documented in ``notes``), never adjusted here.
- Stored values that differ from the file (including a stored value where the
  file says unreported) block ``apply``; equal values are left untouched. The
  import never overwrites entered data.
- Writes go through the same service as the data entry page, so every
  value is recorded in core.audit_events under the actor ``legacy-import``.
"""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from app.core.schemas import CamelModel
from app.db.session import get_sessionmaker
from app.safety import service
from app.safety.repository import DatabaseSafetyMetricsRepository, SafetyMetricsRepository
from app.safety.schemas import CellChange, MonthlyCount, ReportingYear

LEGACY_IMPORT_ACTOR = "legacy-import"
Code = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,100}$")]
Label = Annotated[str, Field(min_length=1, max_length=500)]


class LegacyCategory(CamelModel):
    model_config = ConfigDict(extra="forbid")

    category: Code
    name: Label | None = Field(default=None, description="For reviewers only; not imported.")
    months: Annotated[list[MonthlyCount | None], Field(min_length=12, max_length=12)]


class LegacySection(CamelModel):
    model_config = ConfigDict(extra="forbid")

    section: Code
    name: Label | None = Field(default=None, description="For reviewers only; not imported.")
    categories: Annotated[list[LegacyCategory], Field(min_length=1)]

    @model_validator(mode="after")
    def _categories_are_unique(self) -> Self:
        codes = [c.category for c in self.categories]
        if len(codes) != len(set(codes)):
            raise ValueError(f"categories of section {self.section} must be unique")
        return self


class ExpectedYtd(CamelModel):
    model_config = ConfigDict(extra="forbid")

    section: Code
    category: Code
    value: MonthlyCount
    stated_in: Label


class LegacyMapping(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    metric_set: Code
    year: ReportingYear
    notes: list[Label] = []
    sections: Annotated[list[LegacySection], Field(min_length=1)]
    expected_ytd: list[ExpectedYtd] = []

    @model_validator(mode="after")
    def _sections_are_unique(self) -> Self:
        codes = [s.section for s in self.sections]
        if len(codes) != len(set(codes)):
            raise ValueError("each section may appear only once")
        stated = [(e.section, e.category) for e in self.expected_ytd]
        if len(stated) != len(set(stated)):
            raise ValueError("each expectedYtd category may appear only once")
        return self


@dataclass(frozen=True)
class LegacyCell:
    section: str
    category: str
    month: int
    value: int | None


def cells(mapping: LegacyMapping) -> Iterator[LegacyCell]:
    for section in mapping.sections:
        for category in section.categories:
            for month, value in enumerate(category.months, start=1):
                yield LegacyCell(section.section, category.category, month, value)


@dataclass(frozen=True)
class TotalDiscrepancy:
    section: str
    category: str
    expected: int
    calculated: int | None


def load_mapping(path: Path) -> LegacyMapping:
    return LegacyMapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


def category_ytd(mapping: LegacyMapping) -> dict[tuple[str, str], int | None]:
    return {
        (section.section, category.category): service.total(category.months)
        for section in mapping.sections
        for category in section.categories
    }


def total_discrepancies(mapping: LegacyMapping) -> list[TotalDiscrepancy]:
    ytd = category_ytd(mapping)
    return [
        TotalDiscrepancy(
            section=e.section,
            category=e.category,
            expected=e.value,
            calculated=ytd.get((e.section, e.category)),
        )
        for e in mapping.expected_ytd
        if ytd.get((e.section, e.category)) != e.value
    ]


@dataclass(frozen=True)
class ImportPlan:
    changes: list[CellChange]
    unchanged: int
    unreported: int
    # (section, category, month, stored value, file value; None = unreported in file)
    differing: list[tuple[str, str, int, int, int | None]]
    unknown: list[tuple[str, str]]


def plan_import(repository: SafetyMetricsRepository, mapping: LegacyMapping) -> ImportPlan:
    sections = repository.sections(mapping.metric_set)
    ids = {
        (section.code, category.code): category.id
        for section in sections
        for category in section.categories
    }
    listed = {(s.section, c.category) for s in mapping.sections for c in s.categories}
    unknown = sorted(listed - ids.keys())
    if unknown:
        return ImportPlan(changes=[], unchanged=0, unreported=0, differing=[], unknown=unknown)

    stored = repository.values(sorted(ids.values()), mapping.year)
    changes: list[CellChange] = []
    differing: list[tuple[str, str, int, int, int | None]] = []
    unchanged = unreported = 0
    for cell in cells(mapping):
        category_id = ids[(cell.section, cell.category)]
        current = stored.get((category_id, cell.month))
        if current == cell.value:
            if cell.value is None:
                unreported += 1
            else:
                unchanged += 1
        elif current is None:
            changes.append(
                CellChange(
                    category_id=category_id, month=cell.month, value=cell.value, previous_value=None
                )
            )
        else:
            differing.append((cell.section, cell.category, cell.month, current, cell.value))
    return ImportPlan(
        changes=changes,
        unchanged=unchanged,
        unreported=unreported,
        differing=differing,
        unknown=[],
    )


def _print_check(mapping: LegacyMapping) -> list[TotalDiscrepancy]:
    print(f"Source: {mapping.source}")
    reported = sum(1 for cell in cells(mapping) if cell.value is not None)
    print(
        f"Metric set: {mapping.metric_set}  Year: {mapping.year}  "
        f"Reported cells: {reported}  Unreported cells: {sum(1 for _ in cells(mapping)) - reported}"
    )
    for note in mapping.notes:
        print(f"Note: {note}")
    for (section, category), ytd in category_ytd(mapping).items():
        print(f"  {section}/{category}: YTD {ytd if ytd is not None else 'unreported'}")
    discrepancies = total_discrepancies(mapping)
    for d in discrepancies:
        print(
            f"DISCREPANCY {d.section}/{d.category}: workbook states {d.expected}, "
            f"monthly values sum to {d.calculated if d.calculated is not None else 'nothing'}"
        )
    return discrepancies


def _print_plan(plan: ImportPlan) -> None:
    for section, category in plan.unknown:
        print(f"UNKNOWN category {section}/{category}")
    for section, category, month, current, new in plan.differing:
        shown = "unreported" if new is None else new
        print(f"DIFFERS {section}/{category} month {month}: stored {current}, file {shown}")
    print(
        f"To insert: {len(plan.changes)}  Already stored: {plan.unchanged}  "
        f"Unreported (not written): {plan.unreported}"
    )


def run(command: str, path: Path) -> int:
    try:
        mapping = load_mapping(path)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Invalid mapping file: {error}", file=sys.stderr)
        return 2

    discrepancies = _print_check(mapping)
    if command == "check":
        return 1 if discrepancies else 0

    with get_sessionmaker()() as session:
        repository = DatabaseSafetyMetricsRepository(session)
        plan = plan_import(repository, mapping)
        _print_plan(plan)
        blocked = bool(discrepancies or plan.unknown or plan.differing)
        if command == "plan":
            return 1 if blocked else 0
        if blocked:
            print("Not applied: resolve the issues above first.", file=sys.stderr)
            return 1
        if not plan.changes:
            print("Nothing to apply.")
            return 0
        outcome = service.save_changes(
            repository,
            metric_set=mapping.metric_set,
            year=mapping.year,
            changes=plan.changes,
            actor_id=LEGACY_IMPORT_ACTOR,
            now=dt.datetime.now(dt.UTC),
        )
        print(f"Applied {outcome.changed_cells} values (change set {outcome.change_set_id}).")
    return 0


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.legacy_import")
    parser.add_argument("command", choices=["check", "plan", "apply"])
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    return run(args.command, args.mapping)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
