# Safety release 0009: data-quality report

Prepared 2026-10-08 for review before any production rollout. Every figure
below was produced against the **test** database `operations_platform_test`
(migrated to 0009) or from a copy of the workbook; nothing was written to
production. Discrepancies are reported, not resolved.

Source workbook: `docs/2026 LCY EHS Dash Board.xlsx`, SHA-256
`0B94C09BEDF3C343D3250496780A2D3B66671B55741ABA0391FDE81BE8B51C10`
(unchanged before and after every extraction).

## Incident records (legacy narratives)

Extraction: `python -m app.safety.records.legacy_import extract` with
`import_templates/safety_incident_records_2026_lcy_ehs.extract.json`.

This section covers only individual Incident and Near Miss narrative
passages (sheets `Dash` and `Incident Data`). A record enters the
event-level register only with an actual `incident_date` from the source,
so every "missing date" figure below refers to these passages. The annual
TRIR history (sheet `TRIR EXP.`) is not part of this extraction, and none of
its rows are counted here (see "TRIR").

| Measure | Value |
| --- | --- |
| Commented cells read | 86 |
| Narrative passages found | 108 (Dash 81, Incident Data 27) |
| Candidate records parsed (event passages on Dash area/month cells) | 72 |
| Recommended `include` (valid: event date in its month, description, mapped area) | 15 (high confidence 4, medium 11) |
| Approved `include` (the 15, plus 4 dated in the text; owner decision 2026-10-08) | 19 |
| Excluded | 89 |
| ... no event date in the passage | 53 |
| ... not on the narrative sheet `Dash` (Incident Data repeats / factor lists) | 25 |
| ... label notes outside the area/month cells, not events | 9 |
| ... repeats another passage (`Dash-D40-2`, `Dash-C33-1`) | 2 |
| Candidates missing an incident number | 11 of the 72 event passages, all of them among the 19 included |
| Candidates missing an event date | 53 of the 72 event passages |
| Duplicate incident numbers | none |
| Reclassification / void references | 1: `Dash-G36-1` says it was reclassified from `LCY-2026-036` (excluded: no date), so no link was made |
| PSIF mentions (review only; records have no PSIF field) | 4 |

Ambiguous items needing a reviewer's decision:

- 9 passages may be truncated (no closing punctuation); two are included
  (`Dash-C30-1`, `Dash-F39-4`).
- Classification not resolved, left empty: "Injury" (not a configured
  classification) and twice "Property Damage (Non-Work-Related)" /
  "Non-Work-Related Property Damage" (matches both `non_work_related` and
  `property_damage`). 9 of the 19 included candidates have no classification.
- Resolved 2026-10-08 by owner decision: 4 passages with the event date
  inside the text, not at the start, are included with that date, taken
  verbatim: `Dash-H18-1` (June 24, 2026), `Dash-F39-4` (4/15/2026),
  `Dash-J12-2` (August 15, 2026), `Dash-J39-1` (August 19, 2026). Each date
  lies in its comment's month. The approved file is
  `apps/api/import_templates/safety_incident_records_2026_lcy_ehs.review.json`.
- `LCY-2026-2025` has an unusual sequence number; confirm it.
- A leading date `2/23/23` lies outside its comment's month (February 2026)
  and was not used.
- Numbers written `LCY-2026-30` and `LCY 2026-040` were normalized to
  `LCY-2026-030` and `LCY-2026-040`.

Count by month and event type against the authoritative monthly totals
(the 19 approved records, as rehearsed on the test database):

| Month 2026 | Incident total | Passages | Documented | State | Near Miss total | Passages | Documented | State |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Jan | 5 | 5 | 5 | reconciled | 3 | 3 | 3 | reconciled |
| Feb | 6 | 6 | 5 | records_missing | not reported | 0 | 0 | no_total_and_no_records |
| Mar | 5 | 5 | 2 | records_missing | not reported | 0 | 0 | no_total_and_no_records |
| Apr | 6 | 6 | 1 | records_missing | 11 | 11 | 0 | records_missing |
| May | 3 | 3 | 0 | records_missing | 2 | 2 | 0 | records_missing |
| Jun | 4 | 4 | 0 | records_missing | 4 | 4 | 1 | records_missing |
| Jul | 5 | 5 | 0 | records_missing | 4 | 4 | 0 | records_missing |
| Aug | 3 | 3 | 1 | records_missing | 5 | 5 | 1 | records_missing |
| Sep | 4 | 4 | 0 | records_missing | 2 | 2 | 0 | records_missing |
| Total | 41 | 41 | 14 | | 31 | 31 | 5 | |

- The workbook holds exactly one passage per counted event in every month,
  so the passages agree with the totals. The gap between total and
  documented is entirely passages without an event date (or excluded for
  review); it closes only when reviewers add dates from the source.
- February and March 2026 Near Miss totals are not reported (null), not
  zero.

## Behavior (2026)

Mapping `import_templates/safety_behavior_2026_lcy_ehs.mapping.json`
(`check` passes).

| Measure | Value |
| --- | --- |
| Categories mapped | 24 |
| Categories reported | 10 |
| Blank categories (stored as unreported, not 0) | 14: Housekeeping, Walking & Working Surfaces, Eyes On Task, Hot work, Tool Equipment Selection, Ascending / Descending, PPE Respiratory, Tool Use, Lifting & Lowering, Twisting, Pushing & Pulling, PPE Body, Temp Extreme, Confined Space |
| Total tags | 44 (workbook B29 = 44) |
| Incident denominator | 41, the stored 2026 Incident total (9 months reported, January–September) |
| Tags per incident report | 1.07 |

Calculated percentages (platform, test database):

| Behavior | Tags | Share of tags | Share of incident reports | Cumulative share of tags |
| --- | --- | --- | --- | --- |
| Eyes On Path | 12 | 27.3% | 29.3% | 27.3% |
| Pre & Post Job Inspection | 9 | 20.5% | 22.0% | 47.7% |
| Communications Of Hazards | 4 | 9.1% | 9.8% | 56.8% |
| Knowledge of Task | 4 | 9.1% | 9.8% | 65.9% |
| Energy Isolation | 4 | 9.1% | 9.8% | 75.0% |
| Pinch Points | 3 | 6.8% | 7.3% | 81.8% |
| Get Assistance | 3 | 6.8% | 7.3% | 88.6% |
| Line Of Fire | 2 | 4.5% | 4.9% | 93.2% |
| PPE Hands | 2 | 4.5% | 4.9% | 97.7% |
| PPE Eye | 1 | 2.3% | 2.4% | 100.0% |

Recorded discrepancy: the sheet labels its denominator "Total Number of
Incident Reports 2025" (A30) but B30 is `=Dash!O41`, the 2026 Incident total.
The owner decided all 2026 Behavior data is 2026; the label is kept in the
mapping notes. The denominator is the whole stored year, so it grows as
months are entered.

## TRIR

### Annual history (TRIR EXP.)

TRIR EXP. is an annual source: its columns are the years 2021 to 2026, and
the column heading is the temporal key of every value beneath it. History is
stored by integer `reporting_year` (`safety.trir_annual_facts`, unique per
year) with no date column. No month or day is required, and no date
(such as 31 December) is manufactured. **No annual TRIR row is missing a
date.**

| Year | Recordables | Man-hours | Legacy LCY TRIR | Industry benchmark |
| --- | --- | --- | --- | --- |
| 2021 | 1 | 172,301 | 1.16 | 2.7 |
| 2022 | 3 | 176,350 | 3.4 | 1.9 |
| 2023 | 1 | 168,563 | 1.19 | 1.9 |
| 2024 | 1 | 174,706 | 1.14 | 1.9 |
| 2025 | 0 | 191,751 | 0 | 1.9 |
| 2026 | 1 | 145,194 (legacy snapshot) | 1.3774673884595783 | 1.9 (repeats 2025) |

- 2021–2024 have no monthly hours, so their annual man-hours are the TRIR
  denominator.
- 2025 has full-year monthly hours in Safety Performance and is calculated
  live; its row equals them and is kept for reconciliation.
- From 2026 the live architecture applies: YTD hours come only from Safety
  Performance. The 2026 man-hours (145,194 = January–August, `=Rates!M42`)
  are a legacy snapshot kept for provenance and reconciliation. The
  calculation never uses them as an annual denominator: a year from 2026
  without Safety Performance hours shows TRIR as unavailable.

### Current year (live)

| Measure | Value |
| --- | --- |
| Man-hour metric | Safety Performance "Monthly Hours Worked (Total)" (`safety.performance_hours.total_hours`, hourly + salary where split) |
| Employee / contractor hours | The platform has no contractor-hours field and the source does not say whether contractors are included; nothing is added. **Unconfirmed.** |
| 2026 monthly hours available | January–August, all closed (21,473; 17,654; 18,698; 18,068; 17,366; 17,111; 16,793; 18,031) |
| Missing months | September 2026 onward: not reported (the September month has started) |
| Current YTD denominator | 145,194 hours (January–August 2026) |
| Current recordable numerator | 1 (August 2026; Incident & Near Miss Recordable Injury + Occupational Illness) |
| Calculated TRIR YTD | 1.377467388459578219485653677149193, displayed 1.38 |
| Legacy TRIR (TRIR EXP. M18) | 1.3774673884595783 |
| Difference | about -8 × 10⁻¹⁷ (floating-point noise in the workbook value) |
| Benchmark | 1.9 (2026 row repeats the 2025 figure; a 2026 BLS figure cannot be published yet) |
| Rolling 12 months (Sep 2025–Aug 2026) | 1 recordable, 210,634 hours, 0.95 |

### Historical yearly reconciliation

Recalculated from the approved history:

| Year | Recordables | Hours | Calculated | Legacy | Benchmark | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 2021 | 1 | 172,301 | 1.16 | 1.16 | 2.7 | matches; Safety Performance annual row matches |
| 2022 | 3 | 176,350 | 3.40 | 3.4 | 1.9 | **conflict:** the Rates sheet's 2022 monthly table sums to 425,039.90 hours with 0 recordables; TRIR EXP. is used, conflict unresolved; 2022 is excluded from Safety Performance |
| 2023 | 1 | 168,563 | 1.19 | 1.19 | 1.9 | matches; Safety Performance annual row matches |
| 2024 | 1 | 174,706 | 1.14 | 1.14 | 1.9 | matches; Safety Performance annual row matches |
| 2025 | 0 | 191,751 | 0.00 | 0 | 1.9 | live full year equals the snapshot; the typed Incident count 41 (L9) equals the 2026 count and is not confirmed as 2025 |
| 2026 | 1 | 145,194 | 1.38 | 1.3774673884595783 | 1.9 | live January–August equals the snapshot |

Inconsistencies between Rates, TRIR EXP. and live Safety Performance:

1. 2022: TRIR EXP. (176,350 hours, 3 recordables) versus the Rates 2022
   monthly table (425,039.90 hours, 0 recordables). Unresolved.
2. 2025 Incident count: L9 is a typed 41, identical to the 2026 count.
   Unconfirmed; it feeds only the legacy TIR, never TRIR.
3. 2026 legacy TIR (M17 = 56.48) divides 41 incidents by 145,194 hours.
   The 41 incidents are January–**September** (the stored monthly totals
   sum to 41 through September and 37 through August), while the hours are
   January–**August**. The workbook TIR therefore mixes periods. TIR is shown
   only as a legacy figure, never as TRIR; the platform's live 2026 Incident
   count through August is 37.
4. The benchmark's industry (NAICS) and BLS release year are not stated in
   the source.

## Owner decisions still needed

- Dates (and numbers, where known) for the 53 undated Incident/Near Miss
  narrative passages (this does not apply to the annual TRIR history), and the
  three ambiguous classifications, before importing more records.
- Whether LCY-2026-036 should be imported and linked as reclassified.
- The 2022 TRIR conflict and the 2025 Incident count.
- Whether contractor hours belong in the TRIR denominator.
- The benchmark's industry classification.
