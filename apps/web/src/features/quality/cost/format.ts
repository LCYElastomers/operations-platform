import { MONTH_LABELS } from "@/features/safety/incidents/grid";

import type { CoqClass, CostSummary, FinancialStatus } from "./api";

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

/** Confirmed cost is official; Potential and Validating are exposure and shown apart from it. */
export const FINANCIAL_TONES: Record<FinancialStatus, "warning" | "info" | "success" | "neutral"> = {
  potential: "warning",
  validating: "info",
  confirmed: "success",
  closed: "neutral",
};

export const POTENTIAL_COLOR = "#a16207";

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

export function periodLabel(data: Pick<CostSummary, "year" | "fromMonth" | "throughMonth">): string {
  if (data.year === null) return "No period";
  const first = MONTH_LABELS[data.fromMonth - 1];
  const last = MONTH_LABELS[data.throughMonth - 1];
  return first === last ? `${last} ${data.year}` : `${first}–${last} ${data.year}`;
}

/** ISO dates of the summary's period, for the matching record list. */
export function periodDates(data: Pick<CostSummary, "year" | "fromMonth" | "throughMonth">) {
  if (data.year === null) return { from: "", to: "" };
  const pad = (n: number) => String(n).padStart(2, "0");
  const lastDay = new Date(Date.UTC(data.year, data.throughMonth, 0)).getUTCDate();
  return {
    from: `${data.year}-${pad(data.fromMonth)}-01`,
    to: `${data.year}-${pad(data.throughMonth)}-${pad(lastDay)}`,
  };
}

export function recordsLabel(count: number): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? "record" : "records"}`;
}

/** An ISO date (2026-03-04) as "Mar 4, 2026". */
export function formatDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return `${MONTH_LABELS[month - 1]} ${day}, ${year}`;
}

export function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}
