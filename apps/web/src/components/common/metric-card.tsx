import { cn } from "@/lib/utils";

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
  icon: Icon,
  emphasis = false,
  loading = false,
  className,
}: MetricCardProps) {
  const hasValue =
    typeof value === "string" ? value.length > 0 : value !== null && Number.isFinite(value);
  const valueSize = emphasis ? "text-4xl" : "text-2xl";

  return (
    <div
      className={cn(
        "rounded-lg border bg-card text-card-foreground shadow-xs",
        emphasis ? "p-5" : "p-4",
        className,
      )}
      aria-busy={loading || undefined}
    >
      <div className="flex items-start justify-between gap-2">
        <p
          className={cn(
            "line-clamp-2 font-medium tracking-wide text-muted-foreground uppercase",
            emphasis ? "text-sm" : "text-xs",
          )}
        >
          {label}
        </p>
        {Icon && <Icon className={cn("shrink-0 text-muted-foreground", emphasis ? "size-5" : "size-4")} />}
      </div>
      {loading ? (
        <>
          <div className={cn("mt-3 w-20 animate-pulse rounded bg-muted", emphasis ? "h-9" : "h-6")} />
          <div className="mt-2 h-3 w-28 animate-pulse rounded bg-muted" />
        </>
      ) : (
        <>
          <div className="mt-2 flex min-w-0 items-baseline gap-1">
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
        </>
      )}
    </div>
  );
}
