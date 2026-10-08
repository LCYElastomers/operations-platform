"""Legacy narrative parsing and the review-file rules (no workbook, no database).

Passages below are test fixtures written in the workbook's narrative style.
"""

import datetime as dt
import json
from pathlib import Path

import pytest

from app.safety.records import legacy_import, narratives
from app.safety.records.narratives import CellContext, SourceComment

API_ROOT = Path(__file__).resolve().parents[1]
CONFIG = legacy_import.ExtractConfig.model_validate(
    json.loads(
        (
            API_ROOT / "import_templates" / "safety_incident_records_2026_lcy_ehs.extract.json"
        ).read_text(encoding="utf-8")
    )
)
LABELS = CONFIG.classification_labels
INCIDENT_MARCH = CellContext("incident", "100", "100", 2026, 3)
NEAR_MISS_JUNE = CellContext("near_miss", "lab", "Lab", 2026, 6)


def parse(
    passage: str, context: CellContext = INCIDENT_MARCH
) -> tuple[narratives.Parsed, list[str]]:
    return narratives.parse_passage(passage, context, LABELS)


def test_full_passage_is_parsed() -> None:
    parsed, warnings = parse(
        "3/7/2026 LCY-2026-013 Spill/ Release: Fixture leak at a transmitter. "
        "Contributing Factor: M.I (PSIF)"
    )

    assert parsed.incident_date == dt.date(2026, 3, 7)
    assert parsed.incident_number == "LCY-2026-013"
    assert parsed.classification_code == "spill_release"
    assert (parsed.event_type, parsed.area_code) == ("incident", "100")
    assert parsed.contributing_factor == "M.I"
    assert parsed.psif
    assert warnings == []


def test_a_passage_without_a_date_gets_none() -> None:
    parsed, _ = parse("LCY-2026-030 Spill/ Release: Fixture text.")
    assert parsed.incident_date is None


def test_a_date_outside_the_month_is_not_used() -> None:
    parsed, warnings = parse("2/23/23 - LCY-2026-012 Spill/ Release: Fixture text.")
    assert parsed.incident_date is None
    assert any("outside the comment's month" in w for w in warnings)


def test_dates_in_the_text_are_reported_not_used() -> None:
    parsed, warnings = parse(
        "LCY-2026-047 Near Miss: On June 24, 2026 a fixture flashback occurred.", NEAR_MISS_JUNE
    )
    assert parsed.incident_date is None
    assert parsed.text_dates == ["June 24, 2026"]
    assert any("not used as the event date" in w for w in warnings)


@pytest.mark.parametrize(
    ("raw", "normalized", "warning"),
    [
        ("LCY-2026-30", "LCY-2026-030", "normalized"),
        ("LCY 2026-040", "LCY-2026-040", "normalized"),
        ("LCY-2026-2025", "LCY-2026-2025", "unusual sequence"),
    ],
)
def test_numbers_are_normalized_and_odd_ones_flagged(
    raw: str, normalized: str, warning: str
) -> None:
    parsed, warnings = parse(f"{raw} Near Miss: Fixture text.", NEAR_MISS_JUNE)
    assert parsed.incident_number == normalized
    assert any(warning in w for w in warnings)


def test_missing_number_is_flagged_not_invented() -> None:
    parsed, warnings = parse("3/2/2026 - First Aid: Fixture pinch point.")
    assert parsed.incident_number is None
    assert "No incident number at the start of the passage" in warnings


@pytest.mark.parametrize(
    ("header", "code"),
    [
        ("First Aid", "first_aid"),
        ("Hazardous Condition (Electical)", "hazardous_condition"),
        ("Equipment Damage", "equipment_damage_failure"),
        ("Non-Work-Related Incident", "non_work_related"),
        ("Injury", None),
        ("Non-Work-Related Property Damage", None),
        ("Property Damage (Non-Work-Related)", None),
    ],
)
def test_classifications_resolve_only_when_unambiguous(header: str, code: str | None) -> None:
    parsed, warnings = parse(f"3/2/2026 LCY-2026-001 {header}: Fixture text.")
    assert parsed.classification_code == code
    if code is None:
        assert warnings


def test_reclassification_reference_is_recorded() -> None:
    parsed, warnings = parse(
        "LCY-2026-037 Property Damage: Fixture text. Originally reported as LCY-2026-036 "
        "(Near Miss), reclassified, voiding LCY-2026-036."
    )
    assert parsed.incident_number == "LCY-2026-037"
    assert parsed.reclassified_from == "LCY-2026-036"
    assert parsed.voids == ["LCY-2026-036"]
    assert any("reclassified from" in w for w in warnings)


def test_truncated_passage_is_flagged() -> None:
    _, warnings = parse("3/2/2026 LCY-2026-001 Fire: Fixture text that stops mid inventor")
    assert any("truncated" in w for w in warnings)


def test_block_candidates_split_passages_and_recommend() -> None:
    comment = SourceComment(
        sheet="Dash",
        cell="E27",
        text="Author:\n3/7/2026 LCY-2026-013 Fire: Fixture one.\n\nLCY-2026-014 Fire: Fixture two.",
        cell_value=3,
        author="Author",
    )

    first, second = narratives.block_candidates([(comment, INCIDENT_MARCH)], LABELS)

    assert (first.candidate_id, second.candidate_id) == ("Dash-E27-1", "Dash-E27-2")
    assert (first.recommendation, first.confidence) == ("include", "medium")
    assert second.recommendation == "exclude"
    assert second.exclusion_reason is not None and "No event date" in second.exclusion_reason
    assert any("holds 3 but its comment has 2" in w for w in first.warnings)


def test_duplicate_numbers_keep_only_the_first() -> None:
    a = SourceComment("Dash", "E27", "3/7/2026 LCY-2026-013 Fire: One.", 1)
    b = SourceComment("Dash", "E28", "3/8/2026 LCY-2026-013 Fire: Two.", 1)

    first, second = narratives.block_candidates([(a, INCIDENT_MARCH), (b, INCIDENT_MARCH)], LABELS)

    assert first.recommendation == "include"
    assert second.recommendation == "exclude"


def test_other_sheets_are_excluded_and_repeats_identified() -> None:
    block = narratives.block_candidates(
        [(SourceComment("Dash", "E27", "3/7/2026 LCY-2026-013 Fire: One.", 1), INCIDENT_MARCH)],
        LABELS,
    )
    others = narratives.excluded_candidates(
        [
            SourceComment("Incident Data", "C19", "LCY-2026-013: Fire", 1),
            SourceComment("Incident Data", "P39", "Complacency\nRushing", "Human Performance"),
        ],
        "Not on the narrative sheet",
        block,
    )

    assert [c.recommendation for c in others] == ["exclude", "exclude"]
    assert others[0].exclusion_reason == "Repeats Dash-E27-1"
    assert others[1].exclusion_reason == "Not on the narrative sheet"


def _review(**parsed: object) -> legacy_import.Review:
    passage = "Fixture passage."
    return legacy_import.Review(
        source="fixture",
        workbook_sha256="0" * 64,
        extracted_at=dt.datetime(2026, 10, 8, tzinfo=dt.UTC),
        candidates=[
            legacy_import.ReviewCandidate(
                candidate_id="Dash-E27-1",
                decision="include",
                recommendation="include",
                confidence="high",
                sheet="Dash",
                cell="E27",
                passage_index=1,
                passages_in_cell=1,
                original_passage=passage,
                passage_sha256=narratives.sha256_text(passage),
                parsed=legacy_import.ReviewParsed.model_validate(
                    {
                        "eventType": "incident",
                        "incidentDate": "2026-03-07",
                        "reportingYear": 2026,
                        "reportingMonth": 3,
                        "description": passage,
                        "areaCode": "100",
                        **parsed,
                    }
                ),
            )
        ],
    )


def test_check_accepts_a_complete_included_candidate() -> None:
    assert legacy_import.check_review(_review()) == []


@pytest.mark.parametrize(
    ("parsed", "problem"),
    [
        ({"incidentDate": None}, "no date"),
        ({"incidentDate": "2026-04-01"}, "outside its month"),
        ({"areaCode": None}, "no area"),
    ],
)
def test_check_blocks_incomplete_included_candidates(
    parsed: dict[str, object], problem: str
) -> None:
    assert any(problem in p for p in legacy_import.check_review(_review(**parsed)))


def test_check_detects_an_edited_original_passage() -> None:
    review = _review()
    edited = review.candidates[0].model_copy(update={"original_passage": "changed"})
    review = review.model_copy(update={"candidates": [edited]})
    assert any("edited" in p for p in legacy_import.check_review(review))


def test_the_approved_2026_review_file_passes_check() -> None:
    review = legacy_import.Review.model_validate_json(
        (
            API_ROOT / "import_templates" / "safety_incident_records_2026_lcy_ehs.review.json"
        ).read_text(encoding="utf-8")
    )
    included = {
        c.candidate_id: c.parsed.incident_date for c in review.candidates if c.decision == "include"
    }

    assert legacy_import.check_review(review) == []
    assert len(review.candidates) == 108
    assert len(included) == 19
    # Owner decision 2026-10-08: dates written inside the text, taken verbatim.
    assert {k: included[k] for k in ("Dash-H18-1", "Dash-F39-4", "Dash-J12-2", "Dash-J39-1")} == {
        "Dash-H18-1": dt.date(2026, 6, 24),
        "Dash-F39-4": dt.date(2026, 4, 15),
        "Dash-J12-2": dt.date(2026, 8, 15),
        "Dash-J39-1": dt.date(2026, 8, 19),
    }


def test_source_reference_is_stable_and_internal() -> None:
    review = _review()
    reference = legacy_import.source_reference(review, review.candidates[0])
    assert reference.startswith("legacy-narrative Dash!E27#1 sha256:")
    assert reference == legacy_import.source_reference(review, review.candidates[0])
