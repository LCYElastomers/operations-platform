"""Load reviewed record details (LOPC, damage, PIT, serious risk, further
classifications) onto existing Incident Register records.

    python -m app.safety.records.detail_import check MAPPING.json   # validate, no database
    python -m app.safety.records.detail_import plan  MAPPING.json   # compare with the database
    python -m app.safety.records.detail_import apply MAPPING.json   # write (audited)

The mapping is written by a person from the source documents. Each entry names
one existing record, by incident number or by the legacy narrative passage it
was imported from (``Sheet!Cell#N``), quotes the source text that supports its
values, and gives only values the source states. Nothing is inferred here.

Rules:

- Records are never created. An entry whose record does not exist is a missing
  reference; one whose record is voided or reclassified is a validation failure.
- A value is written only where the record has none. A different stored value
  is a conflict and is never overwritten; an equal one is unchanged. Further
  classifications are only added, never removed.
- Each record is changed through the same service as manual entry (the same
  validation, version increment and audit trail), as ``legacy-import``.
- ``plan`` runs every change inside a transaction it rolls back, so it reports
  exactly what ``apply`` would do: inserts, updates, unchanged, conflicts,
  missing references, invalid codes and validation failures.
- ``apply`` refuses when ``plan`` finds any problem, and otherwise writes every
  record in one transaction: all or nothing. Running it again changes nothing.
"""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from pydantic import ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.schemas import CamelModel
from app.db.session import get_sessionmaker
from app.safety.imports.runs import track_command
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR
from app.safety.records import details, service
from app.safety.records.details import SPECS, DetailSpec
from app.safety.records.models import IncidentRecord
from app.safety.records.repository import RecordRepository
from app.safety.records.schemas import (
    DamageDetails,
    LopcDetails,
    PitDetails,
    RecordUpdate,
    SeriousRiskDetails,
)

IMPORTER = "incident_details"
Label = Annotated[str, Field(min_length=1, max_length=1000)]
Quote = Annotated[str, Field(min_length=1, max_length=2000)]
CODE_ERRORS = ("invalid_code", "invalid_classification")


class MappingEntry(CamelModel):
    model_config = ConfigDict(extra="forbid")

    incident_number: Label | None = None
    legacy_passage: (
        Annotated[str, Field(pattern=r"^[^!]{1,100}![A-Z]{1,3}[0-9]{1,7}#[0-9]{1,3}$")] | None
    ) = None
    # The source text supporting the values, quoted verbatim.
    source_quotes: list[Quote] = Field(min_length=1)
    additional_classification_codes: list[Annotated[str, Field(pattern=r"^[a-z_]{1,60}$")]] = []
    lopc_details: LopcDetails | None = None
    damage_details: DamageDetails | None = None
    pit_details: PitDetails | None = None
    serious_risk_details: SeriousRiskDetails | None = None

    @model_validator(mode="after")
    def _one_reference(self) -> "MappingEntry":
        if (self.incident_number is None) == (self.legacy_passage is None):
            raise ValueError("give exactly one of incidentNumber and legacyPassage")
        return self

    @property
    def reference(self) -> str:
        return self.incident_number or f"passage {self.legacy_passage}"


class Mapping(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    notes: list[Label] = []
    records: list[MappingEntry]


def load_mapping(path: Path) -> Mapping:
    return Mapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


def check_mapping(mapping: Mapping) -> list[str]:
    """Problems found without the database."""
    problems = []
    seen: set[str] = set()
    for entry in mapping.records:
        if entry.reference in seen:
            problems.append(f"{entry.reference}: listed more than once")
        seen.add(entry.reference)
        if not entry.additional_classification_codes and all(
            getattr(entry, spec.field) is None for spec in SPECS
        ):
            problems.append(f"{entry.reference}: gives no detail")
    return problems


# Plan ------------------------------------------------------------------------------


@dataclass
class Plan:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    records_changed: int = 0
    lines: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    missing_references: list[str] = field(default_factory=list)
    invalid_codes: list[str] = field(default_factory=list)
    validation_failures: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        return [
            *(f"CONFLICT {p}" for p in self.conflicts),
            *(f"MISSING {p}" for p in self.missing_references),
            *(f"INVALID CODE {p}" for p in self.invalid_codes),
            *(f"INVALID {p}" for p in self.validation_failures),
        ]


class _InTransaction(RecordRepository):
    """The record service's commits become flushes, so every record's change
    stays in one transaction that the importer commits or rolls back."""

    def commit(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        return None


def _shown(spec: DetailSpec, column: str, value: Any) -> str:
    if column in spec.narrative:
        return "(text)"
    return repr(str(value) if value is not None else None)


def _merge(
    spec: DetailSpec, entry: MappingEntry, stored: dict[str, Any] | None, plan: Plan
) -> dict[str, Any] | None:
    """The detail after filling the stored one from the entry; None when nothing
    changes. Records conflicts in ``plan``."""
    given = getattr(entry, spec.field)
    if given is None:
        return None
    mapped = details.normalized(spec, given)
    columns = [c for c in spec.columns if c in given.model_fields_set and mapped[c] is not None]
    if stored is None:
        plan.inserted += 1
        plan.lines.append(f"{entry.reference}: add {spec.label.lower()}")
        return {c: mapped[c] if c in columns else None for c in spec.columns}
    after = dict(stored)
    filled = []
    for column in columns:
        if stored[column] is None:
            after[column] = mapped[column]
            filled.append(column)
        elif stored[column] != mapped[column]:
            plan.conflicts.append(
                f"{entry.reference}: {spec.label.lower()} {column} is "
                f"{_shown(spec, column, stored[column])}; the mapping gives "
                f"{_shown(spec, column, mapped[column])}"
            )
    if not filled:
        plan.unchanged += 1
        return None
    plan.updated += 1
    plan.lines.append(f"{entry.reference}: fill {spec.label.lower()} {', '.join(filled)}")
    return after


def compare(
    repository: RecordRepository, entry: MappingEntry, plan: Plan
) -> tuple[IncidentRecord, dict[str, Any]] | None:
    """The entry's record and the changes it needs; None when it cannot be
    changed (reported in ``plan``) or needs none. Reads only."""
    record_id = (
        repository.number_owner(entry.incident_number)
        if entry.incident_number
        else repository.legacy_passage_owner(entry.legacy_passage or "")
    )
    if record_id is None:
        plan.missing_references.append(f"{entry.reference}: no such record")
        return None
    row = repository.get(record_id)
    assert row is not None  # noqa: S101 - found above
    record = row.record
    if record.status != "active":
        plan.validation_failures.append(f"{entry.reference}: the record is {record.status}")
        return None

    changes: dict[str, Any] = {}
    classes = {o.code: o for o in repository.classifications()}
    current = repository.further_classification_ids(record_id)
    added = []
    for code in entry.additional_classification_codes:
        option = classes.get(code)
        if option is None or not option.active:
            plan.invalid_codes.append(f"{entry.reference}: classification {code}")
            continue
        if option.id != record.classification_category_id and option.id not in current + added:
            added.append(option.id)
    if added:
        plan.inserted += len(added)
        plan.lines.append(f"{entry.reference}: add classification ids {added}")
        changes["additional_classification_ids"] = current + added
    elif entry.additional_classification_codes:
        plan.unchanged += 1
    conflicts = len(plan.conflicts)
    for spec in SPECS:
        after = _merge(spec, entry, repository.detail(spec, record_id), plan)
        if after is not None:
            changes[spec.field] = spec.schema.model_validate(after)
    if len(plan.conflicts) > conflicts or not changes:
        return None
    return record, changes


def _entry(repository: RecordRepository, entry: MappingEntry, plan: Plan, now: dt.datetime) -> None:
    found = compare(repository, entry, plan)
    if found is None:
        return
    record, changes = found
    try:
        service.update(
            repository,
            record.id,
            RecordUpdate(
                incident_number=record.incident_number,
                incident_date=record.incident_date,
                description=record.description,
                area_id=record.area_id,
                classification_category_id=record.classification_category_id,
                version=record.version,
                **changes,
            ),
            service.Actor(LEGACY_IMPORT_ACTOR, now),
        )
    except service.RecordRuleError as error:
        problems = plan.invalid_codes if error.error in CODE_ERRORS else plan.validation_failures
        problems.append(f"{entry.reference}: {error.message}")
        raise
    plan.records_changed += 1


def run_mapping(session: Session, mapping: Mapping, now: dt.datetime) -> Plan:
    """Apply every entry inside the caller's transaction; each entry in its own
    savepoint, so one failure is reported without hiding the others. The caller
    commits or rolls back."""
    repository = _InTransaction(session)
    plan = Plan()
    for entry in mapping.records:
        savepoint = session.begin_nested()
        try:
            _entry(repository, entry, plan, now)
        except service.RecordRuleError:
            savepoint.rollback()
            continue
        except SQLAlchemyError as error:
            savepoint.rollback()
            plan.validation_failures.append(
                f"{entry.reference}: refused by the database ({type(error).__name__})"
            )
            continue
        savepoint.commit()
    return plan


def _print(plan: Plan) -> None:
    for line in plan.lines:
        print(f"  {line}")
    print(
        f"Inserts: {plan.inserted}  Updates: {plan.updated}  Unchanged: {plan.unchanged}  "
        f"Conflicts: {len(plan.conflicts)}  Missing references: {len(plan.missing_references)}  "
        f"Invalid codes: {len(plan.invalid_codes)}  "
        f"Validation failures: {len(plan.validation_failures)}"
    )
    for problem in plan.problems:
        print(f"PROBLEM {problem}")


# CLI -------------------------------------------------------------------------------


def run(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.records.detail_import")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "plan", "apply"):
        commands.add_parser(name).add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    try:
        mapping = load_mapping(args.mapping)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Invalid mapping file: {error}", file=sys.stderr)
        return 2
    problems = check_mapping(mapping)
    if args.command == "check":
        print(f"Source: {mapping.source}  Entries: {len(mapping.records)}")
        for problem in problems:
            print(f"PROBLEM {problem}")
        return 1 if problems else 0
    if problems:
        for problem in problems:
            print(f"PROBLEM {problem}")
        return 1

    with (
        track_command(IMPORTER, args.command, args.mapping) as run_,
        get_sessionmaker()() as session,
    ):
        plan = run_mapping(session, mapping, dt.datetime.now(dt.UTC))
        _print(plan)
        counts = {
            "inserted": plan.inserted,
            "updated": plan.updated,
            "skipped": plan.unchanged,
            "conflicts": len(plan.conflicts),
            "failed": len(plan.missing_references)
            + len(plan.invalid_codes)
            + len(plan.validation_failures),
        }
        messages = [f"PROBLEM {p}" for p in plan.problems]
        if args.command == "plan" or plan.problems:
            session.rollback()
            run_.finish("blocked" if plan.problems else "planned", **counts, messages=messages)
            if args.command == "apply":
                print("Not applied: resolve the problems above first.", file=sys.stderr)
            return 1 if plan.problems else 0
        if not plan.records_changed:
            session.rollback()
            run_.finish("nothing_to_apply", **counts)
            print("Nothing to apply.")
            return 0
        session.commit()
        run_.finish("applied", **counts)
        print(f"Applied: {plan.records_changed} records changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
