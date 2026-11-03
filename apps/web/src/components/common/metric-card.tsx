import { cn } from "@/lib/utils";

import { panelClassName } from "./panel";

type MetricCardProps = {
  label: string;
  /**
   * Numbers are formatted with `precision`. Strings (identifiers such as a
   * lot or product code) are shown verbatim. null means "no data", which is
   * rendered differently from zero.
   */
  value: number | string | null;
  unit?: string;
  /** Fraction digits for numeric display. */
  precision?: number;
  /** Supporting text, e.g. the period or source of the metric. */
  caption?: string;
  /** A second line under the caption, e.g. a comparison period. */
  detail?: string | null;
  icon?: React.ComponentType<{ className?: string }>;
  /** Larger value for the page's headline metrics. Visual weight only; implies no status. */
  emphasis?: boolean;
  loading?: boolean;
  className?: string;
};

export function MetricCard({
  label,
  value,
  unit,
  precision = 0,
  caption,
  detail,
  icon: Icon,
  emphasis = false,
  loading = false,
  className,
}: MetricCardProps) {
  const hasValue =
    typeof value === "string" ? value.length > 0 : value !== null && Number.isFinite(value);
  const valueSize = emphasis ? "text-3xl" : "text-2xl";

  return (
    <div
      className={cn(panelClassName, emphasis ? "p-3.5" : "p-3", className)}
      aria-busy={loading || undefined}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="line-clamp-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </p>
        {Icon && (
          <Icon
            className={cn("shrink-0 text-muted-foreground", emphasis ? "size-4" : "size-3.5")}
          />
        )}
      </div>
      {loading ? (
        <>
          <div className={cn("mt-2.5 w-20 animate-pulse rounded bg-muted", emphasis ? "h-8" : "h-6")} />
          <div className="mt-1.5 h-3 w-28 animate-pulse rounded bg-muted" />
        </>
      ) : (
        <>
          <div className="mt-1.5 flex min-w-0 items-baseline gap-1">
            {hasValue ? (
              <>
                <span
                  className={cn("truncate font-semibold tracking-tight tabular-nums", valueSize)}
                  title={typeof value === "string" ? value : undefined}
                >
                  {typeof value === "number"
                    ? value.toLocaleString(undefined, {
                        minimumFractionDigits: precision,
                        maximumFractionDigits: precision,
                      })
                    : value}
                </span>
                {unit && <span className="text-sm text-muted-foreground">{unit}</span>}
              </>
            ) : (
              <span
                className={cn("font-semibold tracking-tight text-muted-foreground/60", valueSize)}
              >
                <span aria-hidden>—</span>
                <span className="sr-only">No data</span>
              </span>
            )}
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {hasValue ? caption : (caption ?? "No data")}
          </p>
          {detail && <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">{detail}</p>}
        </>
      )}
    </div>
  );
}
