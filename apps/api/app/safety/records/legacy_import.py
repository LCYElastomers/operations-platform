"""Import legacy Incident & Near Miss narratives as records, after human review.

    # 1. On a workstation (needs the dev dependency openpyxl; reads a COPY of the workbook):
    python -m app.safety.records.legacy_import extract CONFIG.extract.json WORKBOOK.xlsx OUT_DIR
    #    -> OUT_DIR/incident_records_review.json and .csv
    # 2. Review the JSON: set "decision" to include/exclude, fill missing dates
    #    (parsed.incidentDate) only from the source, and correct fields.
    python -m app.safety.records.legacy_import check  REVIEW.json   # validate, no database
    python -m app.safety.records.legacy_import report REVIEW.json   # summary, no database
    python -m app.safety.records.legacy_import plan   REVIEW.json   # compare with the database
    python -m app.safety.records.legacy_import apply  REVIEW.json   # write (audited)

Rules:

- Extraction never writes the workbook and verifies its SHA-256 is unchanged.
- Only candidates whose ``decision`` is ``include`` are imported. ``extract``
  sets ``decision`` to its recommendation; nothing is imported without review.
- An included candidate needs a date in its comment's month, a description,
  a mapped area and, if given, a known classification; otherwise ``check``
  fails. Dates, numbers, areas and classifications are never invented.
- Records are created through the same service as manual entry, with source
  ``legacy_import``, the actor ``legacy-import`` and a source reference
  (passage location and hash) that is audited but never returned by the API.
- ``apply`` is idempotent: a candidate whose source reference is already
  stored is skipped. A number already used by another record blocks ``apply``.
- ``plan`` shows the documented counts by month and type next to the stored
  monthly totals. Records never change the totals.
- Contributing factor and PSIF are reported for review only: records have no
  fields for them, and the passage text (the description) keeps them.
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from app.core.schemas import CamelModel
from app.db.session import get_sessionmaker
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR
from app.safety.records import narratives, service
from app.safety.records.repository import RecordRepository
from app.safety.records.schemas import ReclassifyRequest, RecordCreate

REVIEW_NAME = "incident_records_review"
Label = Annotated[str, Field(min_length=1, max_length=1000)]


# Configuration -------------------------------------------------------------------


class Block(CamelModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["incident", "near_miss"]
    header_row: int = Field(ge=1)
    first_row: int = Field(ge=1)
    last_row: int = Field(ge=1)


class ExtractConfig(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    sheet: Label
    notes: list[Label] = []
    area_column: Annotated[str, Field(pattern=r"^[A-Z]{1,2}$")]
    blocks: list[Block]
    area_labels: dict[str, str]
    classification_labels: dict[str, str]


# Review file ---------------------------------------------------------------------


class ReviewParsed(CamelModel):
    model_config = ConfigDict(extra="forbid")

    incident_number: str | None = None
    raw_incident_number: str | None = None
    event_type: Literal["incident", "near_miss"] | None = None
    incident_date: dt.date | None = None
    reporting_year: int | None = None
    reporting_month: int | None = Field(default=None, ge=1, le=12)
    text_dates: list[str] = []
    description: str
    area_code: str | None = None
    area_label: str | None = None
    classification_code: str | None = None
    classification_label: str | None = None
    contributing_factor: str | None = None
    psif: bool = False
    reclassified_from: str | None = None
    voids: list[str] = []
    related_numbers: list[str] = []


class ReviewCandidate(CamelModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: Label
    decision: Literal["include", "exclude"]
    recommendation: Literal["include", "exclude"]
    exclusion_reason: str | None = None
    confidence: Literal["high", "medium", "low"]
    warnings: list[str] = []
    sheet: Label
    cell: Label
    passage_index: int = Field(ge=1)
    passages_in_cell: int = Field(ge=1)
    cell_value: Any = None
    original_passage: str
    passage_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    parsed: ReviewParsed


class Review(CamelModel):
    model_config = ConfigDict(extra="forbid")

    source: Label
    workbook_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    extracted_at: dt.datetime
    notes: list[Label] = []
    candidates: list[ReviewCandidate]


def load_review(path: Path) -> Review:
    return Review.model_validate(json.loads(path.read_text(encoding="utf-8")))


def source_reference(review: Review, candidate: ReviewCandidate) -> str:
    return (
        f"legacy-narrative {candidate.sheet}!{candidate.cell}#{candidate.passage_index} "
        f"sha256:{candidate.passage_sha256[:16]}"
    )


# Extract -------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(config: ExtractConfig, workbook: Path, now: dt.datetime) -> Review:
    from openpyxl import load_workbook  # dev dependency; extraction runs on a workstation

    before = _sha256(workbook)
    book = load_workbook(workbook, data_only=True)
    if _sha256(workbook) != before:
        raise RuntimeError("the workbook changed while it was read")

    in_blocks: list[tuple[narratives.SourceComment, narratives.CellContext]] = []
    others: list[narratives.SourceComment] = []
    labels: list[narratives.SourceComment] = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.comment is None:
                    continue
                comment = narratives.SourceComment(
                    sheet=sheet.title,
                    cell=cell.coordinate,
                    text=cell.comment.text or "",
                    cell_value=cell.value,
                    author=cell.comment.author,
                )
                if sheet.title != config.sheet:
                    others.append(comment)
                    continue
                block = next(
                    (b for b in config.blocks if b.first_row <= cell.row <= b.last_row), None
                )
                header = sheet.cell(block.header_row, cell.column).value if block else None
                if block is None or not isinstance(header, dt.datetime | dt.date):
                    labels.append(comment)
                    continue
                label = str(sheet[f"{config.area_column}{cell.row}"].value).strip()
                in_blocks.append(
                    (
                        comment,
                        narratives.CellContext(
                            event_type=block.event_type,
                            area_code=config.area_labels.get(label),
                            area_label=label,
                            year=header.year,
                            month=header.month,
                        ),
                    )
                )

    block = narratives.block_candidates(in_blocks, config.classification_labels)
    excluded = narratives.excluded_candidates(
        labels, "A label note outside the area/month cells, not an event", block
    ) + narratives.excluded_candidates(
        others, f"Not on the narrative sheet '{config.sheet}'", block
    )
    if _sha256(workbook) != before:
        raise RuntimeError("the workbook changed while it was read")
    return Review(
        source=config.source,
        workbook_sha256=before,
        extracted_at=now,
        notes=config.notes,
        candidates=[_review_candidate(c) for c in block + excluded],
    )


def _review_candidate(candidate: narratives.Candidate) -> ReviewCandidate:
    return ReviewCandidate(
        candidate_id=candidate.candidate_id,
        decision=candidate.recommendation,
        recommendation=candidate.recommendation,
        exclusion_reason=candidate.exclusion_reason,
        confidence=candidate.confidence,
        warnings=candidate.warnings,
        sheet=candidate.sheet,
        cell=candidate.cell,
        passage_index=candidate.passage_index,
        passages_in_cell=candidate.passages_in_cell,
        cell_value=candidate.cell_value,
        original_passage=candidate.original_passage,
        passage_sha256=candidate.passage_sha256,
        parsed=ReviewParsed.model_validate(asdict(candidate.parsed)),
    )


CSV_COLUMNS = [
    "candidateId",
    "decision",
    "recommendation",
    "exclusionReason",
    "confidence",
    "incidentNumber",
    "rawIncidentNumber",
    "eventType",
    "incidentDate",
    "reportingYear",
    "reportingMonth",
    "areaCode",
    "areaLabel",
    "classificationCode",
    "classificationLabel",
    "contributingFactor",
    "psif",
    "reclassifiedFrom",
    "voids",
    "textDates",
    "warnings",
    "sheet",
    "cell",
    "passageIndex",
    "originalPassage",
]


def write_review(review: Review, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{REVIEW_NAME}.json"
    csv_path = out_dir / f"{REVIEW_NAME}.csv"
    json_path.write_text(review.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for c in review.candidates:
            p = c.parsed
            writer.writerow(
                {
                    "candidateId": c.candidate_id,
                    "decision": c.decision,
                    "recommendation": c.recommendation,
                    "exclusionReason": c.exclusion_reason or "",
                    "confidence": c.confidence,
                    "incidentNumber": p.incident_number or "",
                    "rawIncidentNumber": p.raw_incident_number or "",
                    "eventType": p.event_type or "",
                    "incidentDate": p.incident_date.isoformat() if p.incident_date else "",
                    "reportingYear": p.reporting_year or "",
                    "reportingMonth": p.reporting_month or "",
                    "areaCode": p.area_code or "",
                    "areaLabel": p.area_label or "",
                    "classificationCode": p.classification_code or "",
                    "classificationLabel": p.classification_label or "",
                    "contributingFactor": p.contributing_factor or "",
                    "psif": "yes" if p.psif else "",
                    "reclassifiedFrom": p.reclassified_from or "",
                    "voids": "; ".join(p.voids),
                    "textDates": "; ".join(p.text_dates),
                    "warnings": " | ".join(c.warnings),
                    "sheet": c.sheet,
                    "cell": c.cell,
                    "passageIndex": c.passage_index,
                    "originalPassage": c.original_passage,
                }
            )
    return json_path, csv_path


# Check / report ------------------------------------------------------------------


def check_review(review: Review) -> list[str]:
    """Problems that block importing the included candidates."""
    problems: list[str] = []
    included = [c for c in review.candidates if c.decision == "include"]
    for c in included:
        p = c.parsed
        where = c.candidate_id
        if p.event_type is None:
            problems.append(f"{where}: no event type")
        if p.incident_date is None:
            problems.append(f"{where}: no date of the event")
        elif (
            p.reporting_year
            and p.reporting_month
            and (
                (p.incident_date.year, p.incident_date.month)
                != (p.reporting_year, p.reporting_month)
            )
        ):
            problems.append(f"{where}: date {p.incident_date} is outside its month")
        if not p.description.strip():
            problems.append(f"{where}: empty description")
        if p.area_code is None:
            problems.append(f"{where}: no area")
        if narratives.sha256_text(c.original_passage) != c.passage_sha256:
            problems.append(f"{where}: the original passage was edited")
    numbers = Counter(c.parsed.incident_number for c in included if c.parsed.incident_number)
    problems += [f"{n}: included {k} times" for n, k in numbers.items() if k > 1]
    return problems


def print_report(review: Review) -> None:
    included = [c for c in review.candidates if c.decision == "include"]
    print(f"Source: {review.source}  (workbook SHA-256 {review.workbook_sha256})")
    print(
        f"Candidates: {len(review.candidates)}  Included: {len(included)}  "
        f"Excluded: {len(review.candidates) - len(included)}"
    )
    print("Confidence:", dict(Counter(c.confidence for c in review.candidates)))
    reasons = Counter(c.exclusion_reason for c in review.candidates if c.decision == "exclude")
    for reason, count in reasons.most_common():
        print(f"  excluded ({count}): {reason}")
    by_month = Counter(
        (c.parsed.reporting_year, c.parsed.reporting_month, c.parsed.event_type) for c in included
    )
    for (year, month, event_type), count in sorted(by_month.items(), key=str):
        print(f"  {year}-{month:02d} {event_type}: {count} included")
    warnings = sum(len(c.warnings) for c in review.candidates)
    print(f"Warnings: {warnings} (see the review file)")


# Plan / apply --------------------------------------------------------------------


def _codes(repository: RecordRepository) -> tuple[dict[str, int], dict[str, int]]:
    areas = {o.code: o.id for o in repository.areas() if o.active}
    classes = {o.code: o.id for o in repository.classifications() if o.active}
    return areas, classes


def plan(
    repository: RecordRepository, review: Review
) -> tuple[list[ReviewCandidate], list[str], list[str]]:
    """(to create, already imported ids, blocking problems)."""
    areas, classes = _codes(repository)
    to_create, done, problems = [], [], list(check_review(review))
    for c in (c for c in review.candidates if c.decision == "include"):
        if repository.source_reference_owner(source_reference(review, c)) is not None:
            done.append(c.candidate_id)
            continue
        p = c.parsed
        if p.area_code not in areas:
            problems.append(f"{c.candidate_id}: unknown area {p.area_code}")
        if p.classification_code and p.classification_code not in classes:
            problems.append(f"{c.candidate_id}: unknown classification {p.classification_code}")
        if p.incident_number and repository.number_owner(p.incident_number) is not None:
            problems.append(f"{c.candidate_id}: {p.incident_number} is already used by a record")
        to_create.append(c)
    return to_create, done, problems


def _print_plan(
    repository: RecordRepository, review: Review, to_create: list[ReviewCandidate], done: list[str]
) -> None:
    print(f"To create: {len(to_create)}  Already imported: {len(done)}")
    years = sorted({c.parsed.reporting_year for c in to_create if c.parsed.reporting_year})
    for year in years:
        totals = repository.monthly_totals(year)
        documented = repository.documented_counts(year)
        planned = Counter(
            (c.parsed.event_type, c.parsed.reporting_month)
            for c in to_create
            if c.parsed.reporting_year == year
        )
        for event_type in ("incident", "near_miss"):
            for month in range(1, 13):
                key = (event_type, month)
                if not planned[key] and not documented.get(key):
                    continue
                after = documented.get(key, 0) + planned[key]
                total = totals.get(key)
                state = service.reconciliation_state(total, after)
                print(
                    f"  {year}-{month:02d} {event_type}: total "
                    f"{'unreported' if total is None else total}, documented after import "
                    f"{after} -> {state}"
                )


def apply(repository: RecordRepository, review: Review, now: dt.datetime) -> tuple[int, int]:
    """Create the planned records, then link reclassifications. Returns (created, linked)."""
    to_create, _, problems = plan(repository, review)
    if problems:
        raise RuntimeError("; ".join(problems))
    areas, classes = _codes(repository)
    actor = service.Actor(LEGACY_IMPORT_ACTOR, now)
    created: dict[str, int] = {}
    count = 0
    for c in to_create:
        p = c.parsed
        assert p.incident_date is not None and p.event_type is not None  # noqa: S101 - checked
        row = service.create(
            repository,
            RecordCreate(
                event_type=p.event_type,
                incident_number=p.incident_number,
                incident_date=p.incident_date,
                description=p.description.strip(),
                area_id=areas[p.area_code or ""],
                classification_category_id=classes.get(p.classification_code or ""),
                reporting_year=p.reporting_year,
                reporting_month=p.reporting_month,
            ),
            actor,
            source="legacy_import",
            source_reference=source_reference(review, c),
        )
        count += 1
        if p.incident_number:
            created[p.incident_number] = row.record.id
    linked = 0
    for c in to_create:
        p = c.parsed
        original = created.get(p.reclassified_from or "")
        replacement = created.get(p.incident_number or "")
        if original is None or replacement is None:
            continue
        current = repository.get(original)
        assert current is not None  # noqa: S101 - created above
        service.reclassify(
            repository,
            original,
            ReclassifyRequest(
                version=current.record.version,
                reason=f"Reclassified as {p.incident_number} (legacy narrative)",
                replacement_id=replacement,
            ),
            actor,
        )
        linked += 1
    return count, linked


# CLI -----------------------------------------------------------------------------


def run(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.safety.records.legacy_import")
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract")
    extract_parser.add_argument("config", type=Path)
    extract_parser.add_argument("workbook", type=Path)
    extract_parser.add_argument("out_dir", type=Path)
    for name in ("check", "report", "plan", "apply"):
        commands.add_parser(name).add_argument("review", type=Path)
    args = parser.parse_args(argv)

    if args.command == "extract":
        try:
            config = ExtractConfig.model_validate(
                json.loads(args.config.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, ValidationError) as error:
            print(f"Invalid extract configuration: {error}", file=sys.stderr)
            return 2
        review = extract(config, args.workbook, dt.datetime.now(dt.UTC))
        json_path, csv_path = write_review(review, args.out_dir)
        print_report(review)
        print(f"Wrote {json_path} and {csv_path}. Nothing was imported.")
        return 0

    try:
        review = load_review(args.review)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Invalid review file: {error}", file=sys.stderr)
        return 2
    problems = check_review(review)
    if args.command in ("check", "report"):
        print_report(review)
        for problem in problems:
            print(f"PROBLEM {problem}")
        return 1 if problems else 0

    with get_sessionmaker()() as session:
        repository = RecordRepository(session)
        to_create, done, problems = plan(repository, review)
        _print_plan(repository, review, to_create, done)
        for problem in problems:
            print(f"PROBLEM {problem}")
        if args.command == "plan":
            return 1 if problems else 0
        if problems:
            print("Not applied: resolve the problems above first.", file=sys.stderr)
            return 1
        if not to_create:
            print("Nothing to apply.")
            return 0
        created, linked = apply(repository, review, dt.datetime.now(dt.UTC))
        print(f"Created {created} records; linked {linked} reclassifications.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
