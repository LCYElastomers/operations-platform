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
  loading = false,
  className,
}: MetricCardProps) {
  const hasValue =
    typeof value === "string" ? value.length > 0 : value !== null && Number.isFinite(value);

  return (
    <div
      className={cn("rounded-lg border bg-card p-4 text-card-foreground shadow-xs", className)}
      aria-busy={loading || undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </p>
        {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
      </div>
      {loading ? (
        <>
          <div className="mt-3 h-6 w-20 animate-pulse rounded bg-muted" />
          <div className="mt-2 h-3 w-28 animate-pulse rounded bg-muted" />
        </>
      ) : (
        <>
          <div className="mt-2 flex min-w-0 items-baseline gap-1">
            {hasValue ? (
              <>
                <span
                  className="truncate text-2xl font-semibold tracking-tight tabular-nums"
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
              <span className="text-2xl font-semibold tracking-tight text-muted-foreground/60">
                <span aria-hidden>—</span>
                <span className="sr-only">No data</span>
              </span>
            )}
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {hasValue ? caption : (caption ?? "No data")}
          </p>
        </>
      )}
    </div>
  );
}
