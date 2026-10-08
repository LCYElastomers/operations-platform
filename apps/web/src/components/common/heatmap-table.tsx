import { cn } from "@/lib/utils";

export type HeatmapRow = {
  id: string;
  label: string;
  /** Shown as the row header's tooltip, e.g. an area's full name. */
  description?: string | null;
  /** One per column. null is not reported ("–"); 0 is a reported zero. */
  values: (number | null)[];
  total: number | null;
};

/** A per-column check shown under the column totals, e.g. a reconciliation result. */
export type HeatmapColumnStatus = {
  tone: "ok" | "warning" | "neutral";
  /** Short text in the cell, e.g. "✓" or "+1". */
  text: string;
  /** Full explanation, for the tooltip and screen readers. */
  description: string;
};

type HeatmapTableProps = {
  caption: string;
  rowHeader: string;
  columns: string[];
  rows: HeatmapRow[];
  columnTotals: (number | null)[];
  total: number | null;
  /** Label of the status row; omitted with the statuses. */
  statusLabel?: string;
  statuses?: HeatmapColumnStatus[];
  /** RGB triplet of the shading, e.g. "37 99 235". */
  rgb?: string;
  className?: string;
};

const STATUS_TONES: Record<HeatmapColumnStatus["tone"], string> = {
  ok: "text-success",
  warning: "bg-warning/15 font-semibold text-amber-700 dark:text-warning",
  neutral: "text-muted-foreground",
};

function Count({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <>
        <span aria-hidden className="text-muted-foreground/60">
          –
        </span>
        <span className="sr-only">Not reported</span>
      </>
    );
  }
  return <>{value.toLocaleString()}</>;
}

/**
 * Rows × columns of counts with intensity shading, row and column totals and a
 * pinned row header. Scrolls horizontally inside its card on narrow screens.
 */
export function HeatmapTable({
  caption,
  rowHeader,
  columns,
  rows,
  columnTotals,
  total,
  statusLabel,
  statuses,
  rgb = "37 99 235",
  className,
}: HeatmapTableProps) {
  const max = Math.max(0, ...rows.flatMap((row) => row.values.map((value) => value ?? 0)));
  const shade = (value: number | null) =>
    value === null || value === 0 || max === 0
      ? undefined
      : { backgroundColor: `rgb(${rgb} / ${(0.12 + 0.68 * (value / max)).toFixed(2)})` };
  const dark = (value: number | null) => value !== null && max > 0 && value / max > 0.55;
  const sticky = "sticky left-0 z-10 shadow-[inset_-1px_0_0_var(--color-border)]";

  return (
    <div className={cn("relative overflow-x-auto overscroll-x-contain", className)}>
      <table className="w-full min-w-[640px] border-collapse text-sm tabular-nums">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-muted/60">
          <tr className="border-b">
            <th
              scope="col"
              className={cn(
                "h-9 bg-muted px-3 text-left text-xs font-semibold tracking-wide text-muted-foreground uppercase",
                sticky,
              )}
            >
              {rowHeader}
            </th>
            {columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="h-9 px-2 text-center text-xs font-semibold tracking-wide text-muted-foreground uppercase"
              >
                {column}
              </th>
            ))}
            <th
              scope="col"
              className="h-9 bg-muted px-3 text-right text-xs font-semibold tracking-wide text-foreground uppercase"
            >
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-border/60">
              <th
                scope="row"
                title={row.description ?? undefined}
                className={cn("bg-card px-3 py-1.5 text-left font-medium whitespace-nowrap", sticky)}
              >
                {row.label}
                {row.description && <span className="sr-only"> ({row.description})</span>}
              </th>
              {row.values.map((value, index) => (
                <td
                  key={index}
                  style={shade(value)}
                  className={cn(
                    "h-9 min-w-11 border-l border-border/40 px-2 text-center",
                    dark(value) && "font-semibold text-white",
                  )}
                >
                  <Count value={value} />
                </td>
              ))}
              <td className="bg-muted/60 px-3 text-right font-semibold">
                <Count value={row.total} />
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t-2">
          <tr>
            <th
              scope="row"
              className={cn("h-9 bg-muted px-3 text-left text-xs font-semibold uppercase", sticky)}
            >
              Total
            </th>
            {columnTotals.map((value, index) => (
              <td key={index} className="bg-muted/40 px-2 text-center font-semibold">
                <Count value={value} />
              </td>
            ))}
            <td className="bg-muted px-3 text-right font-semibold">
              <Count value={total} />
            </td>
          </tr>
          {statuses && statusLabel && (
            <tr>
              <th
                scope="row"
                className={cn("h-9 bg-card px-3 text-left text-xs font-medium text-muted-foreground", sticky)}
              >
                {statusLabel}
              </th>
              {statuses.map((status, index) => (
                <td
                  key={index}
                  title={status.description}
                  className={cn("px-2 text-center text-xs", STATUS_TONES[status.tone])}
                >
                  <span aria-hidden>{status.text}</span>
                  <span className="sr-only">{status.description}</span>
                </td>
              ))}
              <td />
            </tr>
          )}
        </tfoot>
      </table>
    </div>
  );
}
