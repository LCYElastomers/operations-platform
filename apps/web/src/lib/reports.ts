/**
 * The web side of the shared export system. A page declares its report key
 * and passes the same period and filters its screen queries use; the API
 * builds the PDF / Excel file (see `apps/api/app/reports`).
 */
import { apiDownload, ApiError } from "@/lib/api-client";
import { periodRequest, type PeriodValue } from "@/lib/period";

export type ReportFormat = "pdf" | "xlsx";

export const FORMAT_LABELS: Record<ReportFormat, string> = {
  pdf: "PDF report",
  xlsx: "Excel workbook",
};

/** What the screen is showing, as the export endpoint takes it. */
export type ReportContext = {
  period: PeriodValue;
  /** The report's filters; empty strings, nulls and empty lists are dropped. `false` is kept (e.g. "not a repeat"). */
  filters: Record<string, unknown>;
};

export function compactFilters(filters: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(filters).filter(
      ([, value]) =>
        value !== null && value !== undefined && value !== "" && !(Array.isArray(value) && value.length === 0),
    ),
  );
}

export function exportBody(format: ReportFormat, context: ReportContext) {
  return { format, period: periodRequest(context.period), filters: compactFilters(context.filters) };
}

/** Requests the file and hands it to the browser as a download; returns its name. */
export async function downloadReport(key: string, format: ReportFormat, context: ReportContext): Promise<string> {
  const { blob, filename } = await apiDownload(`/api/v1/reports/${encodeURIComponent(key)}/export`, exportBody(format, context));
  const name = filename ?? `Operations-Platform_${key}.${format}`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}

export function describeExportError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "You do not have permission to export this report.";
    if (error.status === 401) return "Your session has ended. Sign in again to export.";
    if (error.status === 422) return error.detail?.message ?? "This report cannot be exported for the current selection.";
    if (error.status === 503) return "The database could not be reached. Try again shortly.";
  }
  return "The export could not be generated. Try again.";
}
