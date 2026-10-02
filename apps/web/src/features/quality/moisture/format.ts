import type { TrendSeries } from "@/components/common/trend-chart";

import type { MoistureRecord } from "./api";

/** Display precision only. API values keep full source precision. */
export const MEASUREMENT_PRECISION = {
  avgMoisture: 3,
  avgColor: 2,
  avgCombinedBd: 3,
} as const;

export type Measurement = keyof typeof MEASUREMENT_PRECISION;

export const MISSING = "—";

export function formatMeasurement(value: number | null, precision: number): string {
  if (value === null || !Number.isFinite(value)) return MISSING;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}

/** Formats an ISO date (YYYY-MM-DD) without shifting it through local time zones. */
export function formatSourceDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const UNKNOWN_PRODUCT = "(No product)";

/**
 * One series per product so different products are never joined into a
 * single line. Null measurements stay null and render as gaps.
 */
export function buildTrendSeries(points: MoistureRecord[], measurement: Measurement): TrendSeries[] {
  const byProduct = new Map<string, TrendSeries>();
  for (const point of points) {
    const name = point.product ?? UNKNOWN_PRODUCT;
    let series = byProduct.get(name);
    if (!series) {
      series = { name, points: [] };
      byProduct.set(name, series);
    }
    series.points.push([point.date, point[measurement]]);
  }
  return [...byProduct.values()].sort((a, b) => a.name.localeCompare(b.name));
}
