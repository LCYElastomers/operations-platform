/**
 * TEST FIXTURE ONLY: builders for Incident Analytics responses in unit tests.
 * Not production data and never imported by application code.
 */
import type {
  AnalyticsBreakdown,
  AnalyticsCategory,
  AnalyticsSeries,
  IncidentAnalyticsResponse,
  MonthReconciliation,
  ReconciliationStatus,
} from "./api";

type Values = (number | null)[];

export function fixtureCategory(code: string, name: string, values: Values, extra: Partial<AnalyticsCategory> = {}) {
  const reported = values.filter((value): value is number => value !== null);
  return {
    code,
    name,
    description: null,
    areaKind: null,
    values,
    total: reported.length ? reported.reduce((a, b) => a + b, 0) : null,
    monthsReported: reported.length,
    ...extra,
  } satisfies AnalyticsCategory;
}

function monthlySum(rows: AnalyticsCategory[], months: number): Values {
  return Array.from({ length: months }, (_, index) => {
    const reported = rows.map((row) => row.values[index]).filter((value): value is number => value != null);
    return reported.length ? reported.reduce((a, b) => a + b, 0) : null;
  });
}

export function fixtureBreakdown(
  section: string,
  rows: AnalyticsCategory[],
  months: number,
  isTag = false,
): AnalyticsBreakdown {
  const monthlyTotals = monthlySum(rows, months);
  const reported = monthlyTotals.filter((value): value is number => value !== null);
  const sorted = rows
    .map((row, index) => ({ row, index }))
    .sort(
      (a, b) =>
        Number(a.row.total === null) - Number(b.row.total === null) ||
        (b.row.total ?? 0) - (a.row.total ?? 0) ||
        a.index - b.index,
    )
    .map(({ row }) => row);
  return {
    section,
    name: section,
    isTag,
    categories: sorted,
    rows,
    monthlyTotals,
    total: reported.length ? reported.reduce((a, b) => a + b, 0) : null,
  };
}

export function fixtureReconciliation(dimension: Values, authoritative: Values): MonthReconciliation[] {
  return dimension.map((part, index) => {
    const whole = authoritative[index] ?? null;
    let status: ReconciliationStatus;
    if (whole === null) status = "no_authoritative_total";
    else if (part === null) status = "no_dimension_data";
    else status = part === whole ? "reconciled" : part < whole ? "below_total" : "above_total";
    return {
      month: index + 1,
      dimensionTotal: part,
      authoritativeTotal: whole,
      difference: part !== null && whole !== null ? part - whole : null,
      status,
    };
  });
}

function emptySeries(section: string, code: string, months: number): AnalyticsSeries {
  return {
    section,
    code,
    name: code,
    values: Array.from({ length: months }, () => null),
    total: null,
    monthsReported: 0,
    unreportedMonths: Array.from({ length: months }, (_, index) => index + 1),
    complete: false,
  };
}

type Extras = Omit<
  IncidentAnalyticsResponse,
  | "year"
  | "throughMonth"
  | "latestMonth"
  | "availableYears"
  | "kpis"
  | "incidents"
  | "nearMisses"
  | "classifications"
  | "lopc"
  | "psif"
  | "pit"
  | "propertyDamage"
  | "equipmentDamage"
  | "combinedDamage"
>;

/** The breakdown, prior-year and behavior fields with nothing reported. */
export function emptyAnalyticsExtras(year: number, months: number): Extras {
  const none = Array.from({ length: months }, () => null);
  const empty = (section: string) => fixtureBreakdown(section, [], months);
  return {
    incidentsByArea: [],
    nearMissesByArea: [],
    incidentAreaMonthly: [],
    nearMissAreaMonthly: [],
    areaReconciliation: {
      incidents: fixtureReconciliation(none, none),
      nearMisses: fixtureReconciliation(none, none),
    },
    priorYear: year - 1,
    incidentsPriorYearMonthly: emptySeries("incident_near_miss_totals", "incident", months),
    incidentsPriorYearAvailable: false,
    lopcPriorYearMonthly: emptySeries("lopc", "lopc", months),
    lopcPriorYearAvailable: false,
    lopcContributingFactors: { breakdown: empty("lopc_contributing_factor"), cumulative: [], cumulativeTotal: none },
    lopcFactorReconciliation: fixtureReconciliation(none, none),
    nearMissPotential: fixtureBreakdown("near_miss_potential", [], months, true),
    nearMissCause: fixtureBreakdown("near_miss_cause", [], months, true),
    injuryCause: fixtureBreakdown("injury_cause", [], months, true),
    bodyPart: fixtureBreakdown("body_part", [], months, true),
    injuryReconciliation: {
      injuries: none,
      injuryCause: fixtureReconciliation(none, none),
      bodyPart: fixtureReconciliation(none, none),
    },
    behaviorAvailable: false,
    behaviorData: null,
  };
}
