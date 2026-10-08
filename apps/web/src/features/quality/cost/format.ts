import { MONTH_LABELS } from "@/features/safety/incidents/grid";

import type { CoqClass, CostPeriod } from "./api";

export { MONTH_LABELS };

export const COQ_CLASS_LABELS: Record<CoqClass, string> = {
  prevention: "Prevention",
  appraisal: "Appraisal",
  internal_failure: "Internal Failure",
  external_failure: "External Failure",
};

/** Quadrant colors: good quality costs green and blue, failure costs orange and red. */
export const COQ_CLASS_COLORS: Record<CoqClass, string> = {
  prevention: "#059669",
  appraisal: "#2563eb",
  internal_failure: "#ea580c",
  external_failure: "#dc2626",
};

export function toNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function usd(value: string | null, fractionDigits = 0): string {
  const number = toNumber(value);
  if (number === null) return "—";
  return number.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

/** A fraction (0.0051) as a percentage ("0.51%"). */
export function percent(value: string | null, fractionDigits = 2): string {
  const number = toNumber(value);
  if (number === null) return "—";
  return `${(number * 100).toLocaleString("en-US", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })}%`;
}

export function quantity(value: string | number | null, fractionDigits = 0): string {
  const number = typeof value === "number" ? value : toNumber(value);
  if (number === null) return "—";
  return number.toLocaleString("en-US", { maximumFractionDigits: fractionDigits });
}

export function periodLabel(year: number | null, period: CostPeriod): string {
  if (year === null || period.fromMonth === null || period.throughMonth === null) return "No period";
  const first = MONTH_LABELS[period.fromMonth - 1];
  const last = MONTH_LABELS[period.throughMonth - 1];
  return first === last ? `${last} ${year}` : `${first}–${last} ${year}`;
}

export function reportedLabel(period: CostPeriod): string {
  const { monthsReported, monthsInPeriod } = period;
  return `${monthsReported} of ${monthsInPeriod} ${monthsInPeriod === 1 ? "month" : "months"} reported`;
}
