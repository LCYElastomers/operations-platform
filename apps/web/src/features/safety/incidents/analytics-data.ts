import type { BarSeries, LineSeries } from "@/components/common/bar-chart";
import type { HeatmapColumnStatus } from "@/components/common/heatmap-table";

import type {
  AnalyticsCategory,
  AnalyticsKpi,
  AnalyticsSeries,
  BehaviorAnalytics,
  IncidentAnalyticsResponse,
  MonthReconciliation,
} from "./api";
import { MONTH_LABELS } from "./grid";

export const DASHBOARD_VIEWS = [
  { value: "overview", label: "Overview" },
  { value: "area", label: "Area" },
  { value: "incident-analysis", label: "Incident Analysis" },
  { value: "register", label: "Incident Register" },
  { value: "behavior", label: "Behavior" },
] as const;
export type DashboardView = (typeof DASHBOARD_VIEWS)[number]["value"];

/** The `?view=` value, or Overview when missing or unknown. */
export function parseView(value: string | string[] | null | undefined): DashboardView {
  const text = Array.isArray(value) ? value[0] : value;
  return DASHBOARD_VIEWS.find((view) => view.value === text)?.value ?? "overview";
}

export const KPI_LABELS: Record<AnalyticsKpi["key"], string> = {
  incidents: "Incidents YTD",
  near_misses: "Near Misses YTD",
  lopc: "LOPC YTD",
  psif: "PSIF YTD",
  pit: "PIT Incidents YTD",
  combined_damage: "Property & Equipment Damage YTD",
};

/** Short names for the parts of the combined damage KPI, e.g. "6 property". */
const DAMAGE_PARTS: Record<string, string> = {
  property_damage: "property",
  equipment_damage_failure: "equipment",
};

export const PIT_TITLE = "Powered Industrial Vehicle (PIT) Incidents";

export const NOTES = {
  unreported:
    "A month with no entry is shown as Not reported, never as zero. Totals add the reported months only, so a total with unreported months is not complete.",
  classification:
    "An incident may have more than one classification, so classification counts may exceed the number of incidents.",
  damage:
    "Combined damage is the sum of Property Damage and Equipment Damage classifications. One incident may carry more than one classification.",
  psif: "PSIF counts are displayed as recorded in Incident & Near Miss.",
  psifDefinition: "PSIF is displayed as recorded and is not defined by this analytics page.",
  lopc: "LOPC is the LOPC series. Spill / Release records the same events and is not added to it.",
  pit: "PIT is the Powered Industrial Vehicle Accident classification. The separate PIT block holds the same counts and is not added to it.",
  area: "Area counts are a breakdown of the reported Incident and Near Miss totals, which stay authoritative. A blank area cell is not reported, never zero.",
  lopcFactor:
    "Contributing factors are a breakdown of LOPC, which stays authoritative. A month whose factors do not add up to LOPC is flagged, not changed.",
  tags: "Tags may exceed the event count: one event can carry more than one tag.",
  injuries:
    "Injury cause and body part are compared with First Aid + Recordable Injury. Body parts are tags: one injury can involve more than one.",
  priorYear: "The prior year covers the same months. A month with no entry leaves a gap; 0 is a reported zero.",
  behavior:
    "Behavior counts are annual tags for the whole year, not monthly values, so the Through month does not apply. One incident report can carry more than one behavior tag, so the tags can exceed the incident reports and the shares of incident reports can add up to more than 100%.",
} as const;

export const BEHAVIOR_COLOR = "#2563eb";
export const BEHAVIOR_CUMULATIVE_COLOR = "#0f172a";

/** A fraction as a percentage, e.g. 0.2727 -> "27.3%". */
export function formatShare(value: number | null): string {
  return value === null ? "Not available" : `${(value * 100).toFixed(1)}%`;
}

/** Count bars, highest first, with the cumulative share of tags as a 0–100% line. */
export function behaviorPareto(behavior: BehaviorAnalytics): {
  categories: string[];
  series: BarSeries[];
  lines: LineSeries[];
} {
  const rows = behavior.categories;
  return {
    categories: rows.map((row) => row.name),
    series: [{ name: "Behavior tags", values: rows.map((row) => row.count), color: BEHAVIOR_COLOR }],
    lines: [
      {
        name: "Cumulative % of tags",
        values: rows.map((row) =>
          row.cumulativeShareOfTags === null ? null : Math.round(row.cumulativeShareOfTags * 1000) / 10,
        ),
        color: BEHAVIOR_CUMULATIVE_COLOR,
        axis: "right",
      },
    ],
  };
}

export const PRIOR_YEAR_COLOR = "#94a3b8";

// Categorical, not status colors: no good/bad meaning is implied. Incident and
// Near Miss match the Incident & Near Miss dashboard.
export const COLORS = {
  incidents: "#2563eb",
  nearMisses: "#0d9488",
  lopc: "#7c3aed",
  propertyDamage: "#2563eb",
  equipmentDamage: "#64748b",
  pit: "#0d9488",
  psif: "#7c3aed",
  classification: "#2563eb",
} as const;

/** The latest month of `year` that has started on the Baytown calendar; null for a future year. */
export function latestStartedMonth(year: number, today: { year: number; month: number }): number | null {
  if (year < today.year) return 12;
  if (year === today.year) return today.month;
  return null;
}

export function monthLabels(through: number | null): string[] {
  return MONTH_LABELS.slice(0, through ?? 0);
}

/** e.g. "Jan–Sep 2026", or "Jan 2026" for January alone. */
export function periodLabel(year: number, through: number): string {
  return through === 1 ? `Jan ${year}` : `Jan–${MONTH_LABELS[through - 1]} ${year}`;
}

/** e.g. "Feb, Mar". */
export function monthList(months: number[]): string {
  return months.map((month) => MONTH_LABELS[month - 1]).join(", ");
}

export function formatCount(value: number | null): string {
  return value === null ? "Not reported" : value.toLocaleString();
}

export function kpiCaption(kpi: AnalyticsKpi, year: number): string {
  if (kpi.throughMonth === null) return `${year} has not started`;
  const period = periodLabel(year, kpi.throughMonth);
  if (kpi.monthsReported === 0) return `No months reported, ${period}`;
  if (kpi.complete) {
    return kpi.throughMonth === 1 ? `${period} · reported` : `${period} · all ${kpi.throughMonth} months reported`;
  }
  return `${period} · ${kpi.monthsReported} of ${kpi.throughMonth} months reported`;
}

/**
 * e.g. "6 property · 8 equipment · Jan–Sep 2026, all 9 months reported". A
 * combined month counts as reported only when every part is, so a total built
 * from partly reported parts is labelled partial.
 */
export function combinedKpiCaption(kpi: AnalyticsKpi, year: number): string {
  if (kpi.throughMonth === null || kpi.value === null) return kpiCaption(kpi, year);
  const composition = kpi.parts
    .map((part) => {
      const name = DAMAGE_PARTS[part.code] ?? part.name;
      return part.value === null ? `${name} not reported` : `${part.value.toLocaleString()} ${name}`;
    })
    .join(" · ");
  const period = periodLabel(year, kpi.throughMonth);
  const completeness = kpi.complete
    ? kpi.throughMonth === 1
      ? "reported"
      : `all ${kpi.throughMonth} months reported`
    : `partial, both reported in ${kpi.monthsReported} of ${kpi.throughMonth} months`;
  return `${composition} · ${period}, ${completeness}`;
}

export function findKpi(data: IncidentAnalyticsResponse | undefined, key: AnalyticsKpi["key"]) {
  return data?.kpis.find((kpi) => kpi.key === key);
}

export function bars(series: AnalyticsSeries | undefined, name: string, color: string): BarSeries {
  return { name, color, values: series?.values ?? [] };
}

/** e.g. "Property Damage · 6 YTD"; a total with unreported months is marked partial. */
export function totalLabel(series: AnalyticsSeries): string {
  if (series.total === null) return `${series.name} · not reported`;
  return `${series.name} · ${series.total.toLocaleString()} YTD${series.complete ? "" : " (partial)"}`;
}

export function classificationChart(data: IncidentAnalyticsResponse | undefined): {
  categories: string[];
  series: BarSeries[];
} {
  const rows = data?.classifications ?? [];
  return {
    categories: rows.map((row) => row.name),
    series: [{ name: "YTD", color: COLORS.classification, values: rows.map((row) => row.total) }],
  };
}

/** e.g. "Prior year (Jan–Sep 2025): 36 · +5". Null when the prior year has nothing reported. */
export function priorYearCaption(kpi: AnalyticsKpi | undefined): string | null {
  const prior = kpi?.priorYear;
  if (!prior || prior.value === null || kpi.throughMonth === null) return null;
  const partial = prior.complete ? "" : " (partial)";
  const delta =
    prior.delta === null ? "" : ` · ${prior.delta > 0 ? "+" : prior.delta < 0 ? "−" : "±"}${Math.abs(prior.delta)}`;
  return `Prior year (${periodLabel(prior.year, kpi.throughMonth)}): ${prior.value.toLocaleString()}${partial}${delta}`;
}

/** Reported categories only, as one horizontal bar series in the API's order. */
export function breakdownChart(
  categories: AnalyticsCategory[],
  name: string,
  color: string,
): { categories: string[]; series: BarSeries[]; height: number } {
  const reported = categories.filter((category) => category.total !== null);
  return {
    categories: reported.map((category) => category.name),
    series: [{ name, color, values: reported.map((category) => category.total) }],
    height: Math.max(140, reported.length * 30 + 40),
  };
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/**
 * A month's breakdown compared with its authoritative total, e.g. "+1" with
 * "September: areas total 5, Incidents 4 (1 above)".
 */
export function reconciliationStatus(
  month: MonthReconciliation,
  dimension: string,
  authoritative: string,
): HeatmapColumnStatus {
  const name = MONTH_NAMES[month.month - 1];
  const parts = `${dimension} total ${formatCount(month.dimensionTotal)}`;
  const whole = `${authoritative} ${formatCount(month.authoritativeTotal)}`;
  switch (month.status) {
    case "reconciled":
      return { tone: "ok", text: "✓", description: `${name}: ${parts}, matches ${whole}` };
    case "below_total":
    case "above_total": {
      const difference = month.difference ?? 0;
      return {
        tone: "warning",
        text: difference > 0 ? `+${difference}` : `−${Math.abs(difference)}`,
        description: `${name}: ${parts}, ${whole} (reconciliation difference ${difference > 0 ? "+" : "−"}${Math.abs(difference)})`,
      };
    }
    case "no_dimension_data":
      return { tone: "neutral", text: "–", description: `${name}: no ${dimension} data; ${whole}` };
    case "no_authoritative_total":
      return {
        tone: "neutral",
        text: "n/a",
        description: `${name}: ${authoritative} not reported; ${parts}`,
      };
  }
}

/** e.g. "Reconciled in 7 of 9 months; 2 months have no Near Miss total." */
export function reconciliationSummary(months: MonthReconciliation[], authoritative: string): string {
  if (months.length === 0) return "No months to compare.";
  const count = (status: MonthReconciliation["status"]) =>
    months.filter((month) => month.status === status).length;
  const different = count("below_total") + count("above_total");
  const parts = [`Reconciled in ${count("reconciled")} of ${months.length} months`];
  if (different > 0) parts.push(`${different} with a reconciliation difference`);
  if (count("no_dimension_data") > 0) parts.push(`${count("no_dimension_data")} with no breakdown data`);
  if (count("no_authoritative_total") > 0) {
    parts.push(`${count("no_authoritative_total")} with no ${authoritative} total`);
  }
  return `${parts.join("; ")}.`;
}

/** Series whose period has unreported months, for the data-completeness notes. */
export function incompleteSeries(data: IncidentAnalyticsResponse): { label: string; months: number[] }[] {
  const named: [string, AnalyticsSeries][] = [
    ["Incidents", data.incidents],
    ["Near Misses", data.nearMisses],
    ["LOPC", data.lopc],
    [PIT_TITLE, data.pit],
    [data.propertyDamage.name, data.propertyDamage],
    [data.equipmentDamage.name, data.equipmentDamage],
    ["PSIF", data.psif],
  ];
  return named
    .filter(([, series]) => series.unreportedMonths.length > 0)
    .map(([label, series]) => ({ label, months: series.unreportedMonths }));
}
