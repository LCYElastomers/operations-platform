"""Parse legacy Incident & Near Miss narratives (workbook cell comments) into
candidate records for review.

Pure functions: no workbook or database access. The event type, area and
month come from where the comment sits (its block, row label and column);
everything else comes only from the passage text. Nothing is guessed: a
passage without an explicit leading date gets no date, an unrecognized or
ambiguous classification stays empty, and each uncertainty is a warning.
"""

import calendar
import datetime as dt
import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.safety.records.models import MAX_DESCRIPTION_LENGTH
from app.safety.records.numbers import InvalidIncidentNumberError, normalize_incident_number

Decision = Literal["include", "exclude"]
Confidence = Literal["high", "medium", "low"]

_PASSAGE_BREAK = re.compile(r"\n\s*\n")
_LEADING_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b\s*[-–—:]?\s*")
_NUMBER = re.compile(r"\bLCY[\s_-]*\d{4}[\s_-]+\d{1,6}\b", re.IGNORECASE)
_NUMERIC_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\b")
_MONTH_DATE = re.compile(r"\b(?:" + "|".join(calendar.month_name[1:]) + r")\s+\d{1,2},\s*\d{4}\b")
_CONTRIBUTING = re.compile(r"Contributing Factor:\s*([^\n]+)", re.IGNORECASE)
_PSIF = re.compile(r"\bPSIF\b")
_RECLASSIFIED = re.compile(r"reclassif|originally reported as", re.IGNORECASE)
_VOIDING = re.compile(r"\bvoid(?:ing|ed)?\s+(LCY[\s_-]*\d{4}[\s_-]+\d{1,6})", re.IGNORECASE)
_NEAR_MISS_LABEL = re.compile(r"near[\s-]*miss", re.IGNORECASE)
_TERMINAL = (".", "!", "?", ")", '"', "'", "”")


@dataclass(frozen=True)
class SourceComment:
    sheet: str
    cell: str
    text: str
    # The cell's own value (the monthly count in the area blocks).
    cell_value: object
    author: str | None = None


@dataclass(frozen=True)
class CellContext:
    """Where an area-block comment sits."""

    event_type: Literal["incident", "near_miss"]
    area_code: str | None
    area_label: str
    year: int
    month: int


@dataclass
class Parsed:
    incident_number: str | None = None
    raw_incident_number: str | None = None
    event_type: str | None = None
    incident_date: dt.date | None = None
    reporting_year: int | None = None
    reporting_month: int | None = None
    text_dates: list[str] = field(default_factory=list)
    description: str = ""
    area_code: str | None = None
    area_label: str | None = None
    classification_code: str | None = None
    classification_label: str | None = None
    contributing_factor: str | None = None
    psif: bool = False
    reclassified_from: str | None = None
    voids: list[str] = field(default_factory=list)
    related_numbers: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    candidate_id: str
    sheet: str
    cell: str
    passage_index: int
    passages_in_cell: int
    cell_value: object
    original_passage: str
    passage_sha256: str
    parsed: Parsed
    warnings: list[str] = field(default_factory=list)
    recommendation: Decision = "exclude"
    exclusion_reason: str | None = None
    confidence: Confidence = "low"


def split_passages(text: str, author: str | None = None) -> list[str]:
    body = text.replace("\r\n", "\n")
    if author and body.startswith(f"{author}:"):
        body = body[len(author) + 1 :]
    return [p.strip() for p in _PASSAGE_BREAK.split(body) if p.strip()]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized(raw: str) -> str | None:
    try:
        return normalize_incident_number(raw)
    except InvalidIncidentNumberError:
        return None


def _leading_date(passage: str) -> tuple[dt.date | None, str | None, str]:
    """(date, raw text, the passage without it). An impossible date is (None, raw, ...)."""
    match = _LEADING_DATE.match(passage)
    if match is None:
        return None, None, passage
    month, day, year = (int(g) for g in match.groups())
    if len(match.group(3)) == 2:
        year += 2000
    raw = match.group(0).strip(" -–—:")
    try:
        return dt.date(year, month, day), raw, passage[match.end() :]
    except ValueError:
        return None, raw, passage[match.end() :]


def _classification(
    header: str, labels: Mapping[str, str]
) -> tuple[str | None, str | None, str | None]:
    """(code, label, warning) from the passage header (the text before its first colon)."""
    text = header.lower()
    found = {
        code
        for label, code in labels.items()
        if re.search(rf"(?<![a-z]){re.escape(label)}(?![a-z])", text)
    }
    if len(found) == 1:
        return found.pop(), header, None
    if len(found) > 1:
        return (
            None,
            header,
            (
                f"Classification '{header}' matches several classifications "
                f"({', '.join(sorted(found))}); left empty for review"
            ),
        )
    if header and not _NEAR_MISS_LABEL.search(header):
        return None, header, f"Classification '{header}' is not recognized; left empty for review"
    return None, header or None, None


def parse_passage(
    passage: str, context: CellContext, labels: Mapping[str, str]
) -> tuple[Parsed, list[str]]:
    warnings: list[str] = []
    parsed = Parsed(
        event_type=context.event_type,
        reporting_year=context.year,
        reporting_month=context.month,
        description=passage,
        area_code=context.area_code,
        area_label=context.area_label,
    )
    if context.area_code is None:
        warnings.append(f"Area label '{context.area_label}' is not mapped to an area")

    date, raw_date, rest = _leading_date(passage)
    month_name = f"{calendar.month_name[context.month]} {context.year}"
    if raw_date is not None and date is None:
        warnings.append(f"Leading date '{raw_date}' is not a valid date")
    elif date is not None and (date.year, date.month) != (context.year, context.month):
        warnings.append(
            f"Leading date '{raw_date}' is outside the comment's month ({month_name}); not used"
        )
    elif date is not None:
        parsed.incident_date = date
    rest = rest.lstrip(" -–—:")

    numbers = [(m.start(), m.group(0)) for m in _NUMBER.finditer(rest)]
    if numbers and numbers[0][0] <= 2:
        raw = numbers[0][1]
        parsed.raw_incident_number = raw
        parsed.incident_number = _normalized(raw)
        if parsed.incident_number is not None and parsed.incident_number != raw.strip():
            warnings.append(f"Number '{raw}' normalized to {parsed.incident_number}")
        sequence = parsed.incident_number.rsplit("-", 1)[1] if parsed.incident_number else ""
        if len(sequence) > 3:
            warnings.append(f"Number {parsed.incident_number} has an unusual sequence; confirm it")
        rest = rest[numbers[0][0] + len(raw) :].lstrip(" -–—:")
        numbers = numbers[1:]
    else:
        warnings.append("No incident number at the start of the passage")
    parsed.related_numbers = [n for _, raw in numbers if (n := _normalized(raw))]
    if parsed.related_numbers and _RECLASSIFIED.search(passage):
        parsed.reclassified_from = parsed.related_numbers[0]
        warnings.append(
            f"Says it was reclassified from {parsed.reclassified_from}; link it if that "
            "record is imported"
        )
    parsed.voids = [n for raw in _VOIDING.findall(passage) if (n := _normalized(raw))]

    header = rest.split(":", 1)[0].strip() if ":" in rest[:80] else ""
    code, label, warning = _classification(header, labels)
    parsed.classification_code, parsed.classification_label = code, label
    if warning:
        warnings.append(warning)
    says_near_miss = bool(header and _NEAR_MISS_LABEL.search(header))
    if says_near_miss and context.event_type == "incident":
        warnings.append("The text says Near Miss but the comment is in the Incident block")
    if header and not says_near_miss and context.event_type == "near_miss" and code:
        warnings.append("The text names a classification but the comment is in the Near Miss block")

    factor = _CONTRIBUTING.search(passage)
    if factor:
        parsed.contributing_factor = _PSIF.sub("", factor.group(1)).strip(" .()-")
    parsed.psif = bool(_PSIF.search(passage))

    in_text = _NUMERIC_DATE.findall(rest) + _MONTH_DATE.findall(passage)
    parsed.text_dates = in_text
    if in_text:
        warnings.append(
            f"Date(s) in the text ({'; '.join(in_text)}) are not used as the event date; "
            "confirm the date of the event"
        )
    last_line = passage.splitlines()[-1]
    ends_with_factor = bool(factor and _CONTRIBUTING.search(last_line))
    if not passage.endswith(_TERMINAL) and not ends_with_factor:
        warnings.append("The passage may be truncated (no closing punctuation)")
    if len(passage) > MAX_DESCRIPTION_LENGTH:
        warnings.append(f"The passage is longer than {MAX_DESCRIPTION_LENGTH} characters")
    return parsed, warnings


def _recommend(candidate: Candidate) -> None:
    parsed = candidate.parsed
    reason = None
    if parsed.incident_date is None:
        reason = "No event date in the passage; add the date after checking the source"
    elif len(candidate.original_passage) > MAX_DESCRIPTION_LENGTH:
        reason = "Passage too long for a description"
    elif parsed.area_code is None:
        reason = "Area not mapped"
    candidate.recommendation = "exclude" if reason else "include"
    candidate.exclusion_reason = reason
    if reason:
        candidate.confidence = "low"
    elif candidate.warnings:
        candidate.confidence = "medium"
    else:
        candidate.confidence = "high"


def block_candidates(
    comments: Sequence[tuple[SourceComment, CellContext]], labels: Mapping[str, str]
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for comment, context in comments:
        passages = split_passages(comment.text, comment.author)
        count_warning = None
        if isinstance(comment.cell_value, int | float) and comment.cell_value != len(passages):
            count_warning = (
                f"The cell holds {comment.cell_value:g} but its comment has "
                f"{len(passages)} passage(s)"
            )
        for index, passage in enumerate(passages, start=1):
            parsed, warnings = parse_passage(passage, context, labels)
            if count_warning:
                warnings.append(count_warning)
            candidate = Candidate(
                candidate_id=f"{comment.sheet}-{comment.cell}-{index}",
                sheet=comment.sheet,
                cell=comment.cell,
                passage_index=index,
                passages_in_cell=len(passages),
                cell_value=comment.cell_value,
                original_passage=passage,
                passage_sha256=sha256_text(passage),
                parsed=parsed,
                warnings=warnings,
            )
            _recommend(candidate)
            candidates.append(candidate)

    numbers = Counter(c.parsed.incident_number for c in candidates if c.parsed.incident_number)
    seen: set[str] = set()
    for candidate in candidates:
        number = candidate.parsed.incident_number
        if number and numbers[number] > 1:
            candidate.warnings.append(f"{number} appears in {numbers[number]} passages")
            if number in seen and candidate.recommendation == "include":
                candidate.recommendation = "exclude"
                candidate.exclusion_reason = f"Duplicate of an earlier passage numbered {number}"
            seen.add(number)
    return candidates


def excluded_candidates(
    comments: Sequence[SourceComment], reason: str, block: Sequence[Candidate]
) -> list[Candidate]:
    """Comments outside the narrative blocks, listed for review and never imported."""
    by_number = {c.parsed.incident_number: c for c in block if c.parsed.incident_number}
    by_text = {" ".join(c.original_passage.split()).lower(): c for c in block}
    result = []
    for comment in comments:
        passages = split_passages(comment.text, comment.author)
        for index, passage in enumerate(passages, start=1):
            numbers = [n for raw in _NUMBER.findall(passage) if (n := _normalized(raw))]
            duplicate = next((by_number[n] for n in numbers if n in by_number), None)
            duplicate = duplicate or by_text.get(" ".join(passage.split()).lower())
            result.append(
                Candidate(
                    candidate_id=f"{comment.sheet}-{comment.cell}-{index}",
                    sheet=comment.sheet,
                    cell=comment.cell,
                    passage_index=index,
                    passages_in_cell=len(passages),
                    cell_value=comment.cell_value,
                    original_passage=passage,
                    passage_sha256=sha256_text(passage),
                    parsed=Parsed(description=passage, related_numbers=numbers),
                    recommendation="exclude",
                    exclusion_reason=(
                        f"Repeats {duplicate.candidate_id}" if duplicate is not None else reason
                    ),
                    confidence="low",
                )
            )
    return result
