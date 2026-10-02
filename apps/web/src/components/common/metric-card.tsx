import { cn } from "@/lib/utils";

type MetricCardProps = {
  label: string;
  /** null means "no data", which is rendered differently from zero. */
  value: number | null;
  unit?: string;
  /** Fraction digits for numeric display. */
  precision?: number;
  /** Supporting text, e.g. the period or source of the metric. */
  caption?: string;
  icon?: React.ComponentType<{ className?: string }>;
  className?: string;
};

export function MetricCard({
  label,
  value,
  unit,
  precision = 0,
  caption,
  icon: Icon,
  className,
}: MetricCardProps) {
  const hasValue = value !== null && Number.isFinite(value);

  return (
    <div className={cn("rounded-lg border bg-card p-4 text-card-foreground shadow-xs", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </p>
        {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        {hasValue ? (
          <>
            <span className="text-2xl font-semibold tracking-tight tabular-nums">
              {value.toLocaleString(undefined, {
                minimumFractionDigits: precision,
                maximumFractionDigits: precision,
              })}
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
    </div>
  );
}
