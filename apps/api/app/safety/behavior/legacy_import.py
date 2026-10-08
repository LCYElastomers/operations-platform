"""Import annual Behavior counts from a reviewed mapping file.

    python -m app.safety.behavior.legacy_import check mapping.json   # validate, no database
    python -m app.safety.behavior.legacy_import plan  mapping.json   # compare with stored counts
    python -m app.safety.behavior.legacy_import apply mapping.json   # write (audited)

Rules (as for ``app.safety.legacy_import``):

- One entry per Behavior category, with the workbook label and cell it came
  from. ``null`` means blank in the source and is never written; ``0`` is a
  reported zero.
- ``expectedTotal`` is the total stated in the workbook. A difference from the
  sum of the reported values blocks ``apply``.
- Stored counts that differ from the file (including a stored count where the
  file is blank) block ``apply``; equal counts are left untouched.
- Writes go through the same service as the data entry page and are audited
  under the actor ``legacy-import``.
- The Incident reports denominator is never imported: ``plan`` only shows the
  stored Incident total next to the figure the workbook states.
"""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from app.core.schemas import CamelModel
from app.db.session import get_sessionmaker
from app.safety.analytics import INCIDENTS, METRIC_SET
from app.safety.behavior import service
from app.safety.behavior.repository import BehaviorRepository, DatabaseBehaviorRepository
from app.safety.behavior.schemas import AnnualCount, BehaviorChange
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR
from app.safety.repository import DatabaseSafetyMetricsRepository, SafetyMetricsRepository
from app.safety.schemas import ReportingYear
from app.safety.service import total

Code = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,100}$")]
Label = Annotated[str, Field(min_length=1, max_length=500)]


class BehaviorSourceCount(CamelModel):
    model_config = ConfigDict(extra="forbid")

    category: Code
    source_label: Label = Field(description="The workbook label, verbatim.")
    source_cell: Label
    value: AnnualCount | None


class StatedFigure(CamelModel):
    model_config = ConfigDict(extra="forbid")

    value: AnnualCount
    stated_in: Label


class BehaviorMapping(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    year: ReportingYear
    notes: list[Label] = []
    categories: Annotated[list[BehaviorSourceCount], Field(min_length=1)]
    expected_total: StatedFigure | None = None
    # The workbook's Incident reports figure; compared with the stored total, never imported.
    stated_incident_reports: StatedFigure | None = None

    @model_validator(mode="after")
    def _categories_are_unique(self) -> Self:
        codes = [c.category for c in self.categories]
        if len(codes) != len(set(codes)):
            raise ValueError("each category may appear only once")
        return self


def load_mapping(path: Path) -> BehaviorMapping:
    return BehaviorMapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


def mapping_total(mapping: BehaviorMapping) -> int | None:
    return total(c.value for c in mapping.categories)


@dataclass(frozen=True)
class BehaviorImportPlan:
    changes: list[BehaviorChange]
    unchanged: int
    unreported: int
    # (category, stored value, file value; None = blank in the file)
    differing: list[tuple[str, int, int | None]]
    unknown: list[str]


def plan_import(repository: BehaviorRepository, mapping: BehaviorMapping) -> BehaviorImportPlan:
    ids = {category.code: category.id for category in repository.categories()}
    unknown = sorted(c.category for c in mapping.categories if c.category not in ids)
    if unknown:
        return BehaviorImportPlan(
            changes=[], unchanged=0, unreported=0, differing=[], unknown=unknown
        )
    stored = repository.counts(mapping.year)
    changes: list[BehaviorChange] = []
    differing: list[tuple[str, int, int | None]] = []
    unchanged = unreported = 0
    for entry in mapping.categories:
        current = stored.get(ids[entry.category])
        if current == entry.value:
            if entry.value is None:
                unreported += 1
            else:
                unchanged += 1
        elif current is None:
            changes.append(
                BehaviorChange(
                    category_id=ids[entry.category], value=entry.value, previous_value=None
                )
            )
        else:
            differing.append((entry.category, current, entry.value))
    return BehaviorImportPlan(
        changes=changes,
        unchanged=unchanged,
        unreported=unreported,
        differing=differing,
        unknown=[],
    )


def stored_incident_reports(repository: SafetyMetricsRepository, year: int) -> int | None:
    """The stored Incident total for ``year`` (sum of its reported months)."""
    category = next(
        (
            c
            for s in repository.sections(METRIC_SET)
            if s.code == INCIDENTS[0]
            for c in s.categories
            if c.code == INCIDENTS[1]
        ),
        None,
    )
    if category is None:
        return None
    stored = repository.values([category.id], year)
    return total(stored.get((category.id, month)) for month in range(1, 13))


def _print_check(mapping: BehaviorMapping) -> bool:
    """Prints the file summary; returns True when the stated total disagrees."""
    print(f"Source: {mapping.source}")
    reported = [c for c in mapping.categories if c.value is not None]
    print(
        f"Year: {mapping.year}  Reported categories: {len(reported)}  "
        f"Blank (not written): {len(mapping.categories) - len(reported)}"
    )
    for note in mapping.notes:
        print(f"Note: {note}")
    for entry in mapping.categories:
        shown = entry.value if entry.value is not None else "blank"
        print(f"  {entry.category} ({entry.source_cell} '{entry.source_label}'): {shown}")
    calculated = mapping_total(mapping)
    print(f"Total of reported categories: {calculated if calculated is not None else 'nothing'}")
    stated = mapping.expected_total
    if stated is not None and stated.value != calculated:
        print(
            f"DISCREPANCY total: workbook states {stated.value} ({stated.stated_in}), "
            f"categories sum to {calculated if calculated is not None else 'nothing'}"
        )
        return True
    return False


def _print_plan(plan: BehaviorImportPlan) -> None:
    for category in plan.unknown:
        print(f"UNKNOWN category {category}")
    for category, current, new in plan.differing:
        print(f"DIFFERS {category}: stored {current}, file {'blank' if new is None else new}")
    print(
        f"To insert: {len(plan.changes)}  Already stored: {plan.unchanged}  "
        f"Blank (not written): {plan.unreported}"
    )


def run(command: str, path: Path) -> int:
    try:
        mapping = load_mapping(path)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Invalid mapping file: {error}", file=sys.stderr)
        return 2

    discrepancy = _print_check(mapping)
    if command == "check":
        return 1 if discrepancy else 0

    with get_sessionmaker()() as session:
        repository = DatabaseBehaviorRepository(session)
        plan = plan_import(repository, mapping)
        _print_plan(plan)
        reports = stored_incident_reports(DatabaseSafetyMetricsRepository(session), mapping.year)
        stated = mapping.stated_incident_reports
        print(
            f"Incident reports (stored Incident total, the denominator): "
            f"{reports if reports is not None else 'not reported'}"
            + (f"; workbook states {stated.value} ({stated.stated_in})" if stated else "")
        )
        blocked = bool(discrepancy or plan.unknown or plan.differing)
        if command == "plan":
            return 1 if blocked else 0
        if blocked:
            print("Not applied: resolve the issues above first.", file=sys.stderr)
            return 1
        if not plan.changes:
            print("Nothing to apply.")
            return 0
        outcome = service.save_counts(
            repository,
            year=mapping.year,
            changes=plan.changes,
            actor_id=LEGACY_IMPORT_ACTOR,
            now=dt.datetime.now(dt.UTC),
        )
        print(f"Applied {outcome.changed_categories} counts (change set {outcome.change_set_id}).")
    return 0


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.behavior.legacy_import")
    parser.add_argument("command", choices=["check", "plan", "apply"])
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    return run(args.command, args.mapping)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
