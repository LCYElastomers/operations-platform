import type { BarSeries } from "@/components/common/bar-chart";

import type { AnalyticsKpi, AnalyticsSeries, IncidentAnalyticsResponse } from "./api";
import { MONTH_LABELS } from "./grid";

export const KPI_LABELS: Record<AnalyticsKpi["key"], string> = {
  incidents: "Incidents YTD",
  near_misses: "Near Misses YTD",
  lopc: "LOPC YTD",
  psif: "PSIF YTD",
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
} as const;

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
