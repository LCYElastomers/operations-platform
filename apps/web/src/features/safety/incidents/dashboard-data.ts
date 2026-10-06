import type { BarSeries } from "@/components/common/bar-chart";

import type { MetricCategoryRow, MonthlyMetricsResponse } from "./api";
import { MONTH_LABELS } from "./grid";

const TOTALS = "incident_near_miss_totals";
const CLASSIFICATION = "incident_classification";

/**
 * KPI cards, in display order. Each shows the YTD of one explicit source
 * metric; Incident is never the sum of Incident Classification.
 */
export const KPI_METRICS = [
  { sectionCode: TOTALS, categoryCode: "incident", label: "Incident YTD" },
  { sectionCode: TOTALS, categoryCode: "near_miss", label: "Near Miss YTD" },
  { sectionCode: "lopc", categoryCode: "lopc", label: "LOPC YTD" },
  {
    sectionCode: "property_equipment_damage",
    categoryCode: "property_equipment_damage",
    label: "Property / Equipment Damage YTD",
  },
  { sectionCode: "pit", categoryCode: "pit", label: "PIT YTD" },
  { sectionCode: "psif", categoryCode: "psif", label: "PSIF YTD" },
] as const;

export type KpiCategoryCode = (typeof KPI_METRICS)[number]["categoryCode"];

export function findMetric(
  metrics: MonthlyMetricsResponse | undefined,
  sectionCode: string,
  categoryCode: string,
): MetricCategoryRow | undefined {
  return metrics?.sections
    .find((section) => section.code === sectionCode)
    ?.categories.find((category) => category.code === categoryCode);
}

/** e.g. "Jan–Mar 2026"; describes which months a YTD value covers. */
export function reportedPeriod(metric: MetricCategoryRow | undefined, year: number): string {
  const months = metric?.values ?? [];
  const reported = months.flatMap((value, index) => (value === null ? [] : [index]));
  if (reported.length === 0) return `No months reported for ${year}`;
  const first = MONTH_LABELS[reported[0]];
  const last = MONTH_LABELS[reported[reported.length - 1]];
  return first === last ? `${first} ${year}` : `${first}–${last} ${year}`;
}

export function incidentsVsNearMisses(metrics: MonthlyMetricsResponse | undefined): BarSeries[] {
  const unreported = MONTH_LABELS.map(() => null);
  return [
    { name: "Incidents", values: findMetric(metrics, TOTALS, "incident")?.values ?? unreported },
    {
      name: "Near Misses",
      values: findMetric(metrics, TOTALS, "near_miss")?.values ?? unreported,
    },
  ];
}

export function classificationBreakdown(metrics: MonthlyMetricsResponse | undefined): {
  categories: string[];
  series: BarSeries[];
} {
  const categories =
    metrics?.sections.find((section) => section.code === CLASSIFICATION)?.categories ?? [];
  return {
    categories: categories.map((category) => category.name),
    series: [{ name: "YTD", values: categories.map((category) => category.ytd) }],
  };
}
