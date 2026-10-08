# Cost of Quality (migration 0010): data-quality report

Sources, read from copies; the originals were not modified:

| Workbook | SHA-256 |
| -------- | ------- |
| `COQ Matrix.xlsx` | `5C1452D50A14606CF7798B2B7EAC2925D189A5C88304C3D961DBA87857C83840` |
| `Cost for Poor Quality Control-R0-08122025.xlsx` | `DDBA947AFDCFCF5957DB6FF7C4268A2FF699508D815400AB18A4335EFFB832B2` |

## COQ Matrix workbook (monthly figures)

Imported: 202601 and 202602. Recalculated internal and external failure match
the workbook's totals to the cent:

| Month | Internal failure | External failure | COPQ | Sales revenue | COPQ % of sales |
| ----- | ---------------: | ---------------: | ---: | ------------: | --------------: |
| Jan 2026 | $25,435.17 | $26,720.00 | $52,155.17 | $10,259,998 | 0.51% |
| Feb 2026 | $20,991.75 | $2,800.00 | $23,791.75 | $11,506,662 | 0.21% |
| Jan–Feb | $46,426.92 | $29,520.00 | $75,946.92 | $21,766,660 | 0.35% |

Findings:

1. **No prevention or appraisal costs.** The workbook records failure costs
   only. Prevention, appraisal, Good COQ, Total COQ and Poor COQ % are shown as
   not recorded, never $0.
2. **"Production Value ($)" is pounds.** COQ!D links to Production!C, total
   production in lb. The workbook's "Production COQ %" therefore divides
   dollars by pounds, and "Total Cost of Poor Quality %" divides by pounds plus
   dollars. Neither is imported. The platform shows production cost per pound
   produced and computes percentages against sales revenue only, as the
   Definitions sheet describes.
3. **January off-spec is blank.** Production!E3 is empty; the workbook counts
   it as $0. It is stored as not reported and listed as a data check.
4. **Warehousing and complaint rework are formulas**, not measured costs:
   returned lb × $0.02 and × $0.34. Their results are imported. 14280.000000000002
   (floating-point) is imported as 14280.
5. **March to December are blank** in every sheet and are not stored. The
   Production sheet has no 202612 row.
6. **Scrap and off-spec loss rates are constants** in Production Cost (0.61 and
   0.338 $/lb), not derived from the monthly raw-material prices on that sheet.
7. **No area, product, owner, status, target or action** fields exist, so those
   filters and an action register are not available. Open items, days open and
   recovery are shown as not tracked.

## COPQ workbook (incident estimator)

Not imported: it is a calculator with one example incident. Its method and
parameters drive the estimator; nothing it calculates is stored. Findings:

1. The Rework sheet's total (C39) leaves out the calculated steam and power
   cost (C25) despite its label. Reproduced as written; the energy cost is shown
   separately.
2. Product lookups use VLOOKUP with approximate match on an unsorted table; the
   estimator requires an exact match.
3. Summary!C15 offers product 3142, which has no standard rate.
4. Summary D8 and D9 have their descriptions swapped (rework vs repack).
5. The Cgrade sheet's title says "Scrap".
6. The Rework sheet's "Will it cause lower production rate" lookup (B5) is not
   used by any formula.
7. Pound conversions use 0.454 in some formulas and 2.2 in others.
8. Prices and margins are the R0 (12 Aug 2025) values.
