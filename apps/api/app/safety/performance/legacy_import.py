"""Import historical worked hours and annual TRIR history from a reviewed mapping.

Pre-2026 monthly event counts are not handled here: they are monthly metrics in
the ``performance_legacy`` set and load with ``app.safety.legacy_import``. This
module loads ``safety.performance_hours`` and ``safety.performance_annual_legacy``.
It is not used by the API, and migrations never run it.

    python -m app.safety.performance.legacy_import check  mapping.json  # validate, no database
    python -m app.safety.performance.legacy_import plan   mapping.json  # compare with stored rows
    python -m app.safety.performance.legacy_import apply  mapping.json  # write (audited)

Rules:

- Closure is never inferred from hours being present. ``monthClosed: true``
  requires ``closedBasis``, the source fact or owner confirmation that closes
  the month. For an Incident & Near Miss year it confirms the month's counts
  are complete (absent counts become zeros). For a legacy year it does not:
  blank legacy counts stay unconfirmed and block that measure's windows.
- ``statedIn`` and ``closedBasis`` are recorded in the audit event.
- ``expectedHours`` records hour totals stated elsewhere in the workbook. Any
  difference from the sum of the months is reported and blocks ``apply``.
- ``excludedYears`` documents years deliberately left out; the file may not
  contain hours or annual rows for them.
- An annual row is only for a year without monthly hours.
- Stored rows that differ from the file block ``apply``; equal rows are left
  untouched. The import never overwrites entered data.
- Every inserted row is recorded in core.audit_events under ``legacy-import``.
"""

import argparse
import datetime as dt
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Self

from pydantic import ConfigDict, Field, StrictBool, StrictInt, ValidationError, model_validator

from app.audit.recorder import AuditChange
from app.core.schemas import CamelModel
from app.db.session import get_sessionmaker
from app.safety.contacts.service import site_today
from app.safety.performance import service
from app.safety.performance.models import MAX_SOURCE_LENGTH
from app.safety.performance.repository import (
    AnnualValues,
    DatabasePerformanceRepository,
    HoursValues,
    PerformanceRepository,
)
from app.safety.performance.schemas import Hours
from app.safety.schemas import ReportingMonth, ReportingYear

LEGACY_IMPORT_ACTOR = "legacy-import"
Label = Annotated[str, Field(min_length=1, max_length=MAX_SOURCE_LENGTH)]


class HoursEntry(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: ReportingYear
    month: ReportingMonth
    total_hours: Hours
    hourly_hours: Hours | None = None
    salary_hours: Hours | None = None
    month_closed: StrictBool
    stated_in: Label
    closed_basis: Label | None = None

    @model_validator(mode="after")
    def _closure_is_sourced(self) -> Self:
        if self.month_closed != (self.closed_basis is not None):
            raise ValueError(
                f"{self.year}-{self.month:02d}: closedBasis is required for a closed month "
                "and allowed only for one"
            )
        return self

    @model_validator(mode="after")
    def _breakdown_adds_up(self) -> Self:
        if (
            self.hourly_hours is not None
            and self.salary_hours is not None
            and self.hourly_hours + self.salary_hours != self.total_hours
        ):
            raise ValueError(f"{self.year}-{self.month:02d}: hourly + salary must equal total")
        return self

    def values(self) -> HoursValues:
        return service.normalized(
            HoursValues(self.total_hours, self.hourly_hours, self.salary_hours, self.month_closed)
        )


class AnnualEntry(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: ReportingYear
    recordables: Annotated[StrictInt, Field(ge=0)]
    total_hours: Annotated[Hours, Field(gt=0)]
    source: Label

    def values(self) -> AnnualValues:
        return AnnualValues(
            self.recordables, self.total_hours.quantize(Decimal("0.01")), self.source.strip()
        )


class ExpectedHours(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: ReportingYear
    through_month: ReportingMonth
    total_hours: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    stated_in: Label


class ExcludedYear(CamelModel):
    model_config = ConfigDict(extra="forbid")

    year: ReportingYear
    reason: Label


class PerformanceMapping(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    notes: list[Label] = []
    hours: list[HoursEntry] = []
    annual: list[AnnualEntry] = []
    expected_hours: list[ExpectedHours] = []
    excluded_years: list[ExcludedYear] = []

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        months = [(h.year, h.month) for h in self.hours]
        if len(months) != len(set(months)):
            raise ValueError("each month may appear only once in hours")
        annual_years = [a.year for a in self.annual]
        if len(annual_years) != len(set(annual_years)):
            raise ValueError("each year may appear only once in annual")
        hour_years = {year for year, _ in months}
        if both := sorted(hour_years & set(annual_years)):
            raise ValueError(f"years with monthly hours cannot have an annual row: {both}")
        excluded = {e.year for e in self.excluded_years}
        if listed := sorted(excluded & (hour_years | set(annual_years))):
            raise ValueError(f"excluded years may not have rows: {listed}")
        return self


def load_mapping(path: Path) -> PerformanceMapping:
    return PerformanceMapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class HoursDiscrepancy:
    year: int
    through_month: int
    expected: Decimal
    # None when a month in the range is missing from the file.
    calculated: Decimal | None


def hours_discrepancies(mapping: PerformanceMapping) -> list[HoursDiscrepancy]:
    by_month = {(h.year, h.month): h.total_hours for h in mapping.hours}
    found = []
    for e in mapping.expected_hours:
        periods = [(e.year, m) for m in range(1, e.through_month + 1)]
        calculated = (
            sum((by_month[p] for p in periods), Decimal(0))
            if all(p in by_month for p in periods)
            else None
        )
        if calculated != e.total_hours:
            found.append(HoursDiscrepancy(e.year, e.through_month, e.total_hours, calculated))
    return found


@dataclass
class ImportPlan:
    hours: list[HoursEntry] = field(default_factory=list)
    annual: list[AnnualEntry] = field(default_factory=list)
    unchanged: int = 0
    # Human-readable reasons apply is refused.
    blocking: list[str] = field(default_factory=list)


def plan_import(
    repository: PerformanceRepository, mapping: PerformanceMapping, *, today: dt.date
) -> ImportPlan:
    plan = ImportPlan()
    stored_hours = repository.hours()
    stored_annual = repository.annual_legacy()
    stored_years = {year for year, _ in stored_hours}

    for entry in mapping.hours:
        label = f"{entry.year}-{entry.month:02d}"
        if entry.month_closed and (entry.year, entry.month) >= (today.year, today.month):
            plan.blocking.append(f"{label}: closed in the file but the month has not ended")
        current = stored_hours.get((entry.year, entry.month))
        if current is None:
            plan.hours.append(entry)
        elif current.values == entry.values():
            plan.unchanged += 1
        else:
            plan.blocking.append(
                f"{label}: stored {service.hours_audit_value(current.values)}, "
                f"file {service.hours_audit_value(entry.values())}"
            )

    for entry in mapping.annual:
        if entry.year in stored_years:
            plan.blocking.append(f"{entry.year}: monthly hours are stored; annual row not allowed")
            continue
        current_annual = stored_annual.get(entry.year)
        if current_annual is None:
            plan.annual.append(entry)
        elif current_annual.values == entry.values():
            plan.unchanged += 1
        else:
            plan.blocking.append(f"{entry.year}: stored annual row differs from the file")
    return plan


def apply_plan(
    repository: PerformanceRepository, plan: ImportPlan, *, now: dt.datetime
) -> uuid.UUID:
    """Insert the planned rows in one audited transaction."""
    change_set = uuid.uuid4()
    changes: list[AuditChange] = []
    try:
        for entry in plan.hours:
            repository.lock_month(entry.year, entry.month)
            if repository.get_hours(entry.year, entry.month) is not None:
                raise RuntimeError(f"{entry.year}-{entry.month:02d} was stored meanwhile")
            values = entry.values()
            repository.insert_hours(
                entry.year, entry.month, values, actor_id=LEGACY_IMPORT_ACTOR, at=now
            )
            changes.append(
                AuditChange(
                    action="create",
                    entity_type=service.HOURS_ENTITY_TYPE,
                    entity_key=service.hours_key(entry.year, entry.month),
                    old_value=None,
                    new_value={
                        **service.hours_audit_value(values),
                        "stated_in": entry.stated_in,
                        "closed_basis": entry.closed_basis,
                    },
                )
            )
        for annual in plan.annual:
            repository.lock_annual(annual.year)
            if annual.year in repository.annual_legacy():
                raise RuntimeError(f"annual {annual.year} was stored meanwhile")
            values_ = annual.values()
            repository.insert_annual(annual.year, values_, actor_id=LEGACY_IMPORT_ACTOR, at=now)
            changes.append(
                AuditChange(
                    action="create",
                    entity_type=service.ANNUAL_ENTITY_TYPE,
                    entity_key=service.annual_key(annual.year),
                    old_value=None,
                    new_value={
                        "recordables": values_.recordables,
                        "total_hours": f"{values_.total_hours:.2f}",
                        "source": values_.source,
                    },
                )
            )
        repository.record_audit(
            changes, actor_id=LEGACY_IMPORT_ACTOR, change_set_id=change_set, at=now
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    return change_set


def _print_check(mapping: PerformanceMapping) -> list[HoursDiscrepancy]:
    print(f"Source: {mapping.source}")
    closed = sum(1 for h in mapping.hours if h.month_closed)
    print(
        f"Hours months: {len(mapping.hours)} ({closed} closed)  Annual rows: {len(mapping.annual)}"
    )
    for note in mapping.notes:
        print(f"Note: {note}")
    for excluded in mapping.excluded_years:
        print(f"Excluded {excluded.year}: {excluded.reason}")
    discrepancies = hours_discrepancies(mapping)
    for d in discrepancies:
        shown = "incomplete months" if d.calculated is None else d.calculated
        print(
            f"DISCREPANCY {d.year} Jan-{d.through_month:02d}: workbook states {d.expected}, "
            f"months sum to {shown}"
        )
    return discrepancies


def run(command: str, path: Path) -> int:
    try:
        mapping = load_mapping(path)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Invalid mapping file: {error}", file=sys.stderr)
        return 2

    discrepancies = _print_check(mapping)
    if command == "check":
        return 1 if discrepancies else 0

    now = dt.datetime.now(dt.UTC)
    with get_sessionmaker()() as session:
        repository = DatabasePerformanceRepository(session)
        plan = plan_import(repository, mapping, today=site_today(now))
        for reason in plan.blocking:
            print(f"BLOCKED {reason}")
        print(
            f"To insert: {len(plan.hours)} months, {len(plan.annual)} annual rows  "
            f"Already stored: {plan.unchanged}"
        )
        blocked = bool(discrepancies or plan.blocking)
        if command == "plan":
            return 1 if blocked else 0
        if blocked:
            print("Not applied: resolve the issues above first.", file=sys.stderr)
            return 1
        if not plan.hours and not plan.annual:
            print("Nothing to apply.")
            return 0
        change_set = apply_plan(repository, plan, now=now)
        print(f"Applied {len(plan.hours) + len(plan.annual)} rows (change set {change_set}).")
    return 0


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.performance.legacy_import")
    parser.add_argument("command", choices=["check", "plan", "apply"])
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args(argv)
    return run(args.command, args.mapping)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
