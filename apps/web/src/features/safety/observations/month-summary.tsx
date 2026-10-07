import { cn } from "@/lib/utils";

import type { CategoryCount, ObservationCounts } from "./api";
import { categoriesWithObservations, summaryTiles } from "./observation-data";

type MonthSummaryProps = {
  /** e.g. "October 2026" */
  period: string;
  counts: ObservationCounts | undefined;
  categories: CategoryCount[];
  loading?: boolean;
};

/** Counts for the selected month. Every figure counts the same observation records. */
export function MonthSummary({ period, counts, categories, loading = false }: MonthSummaryProps) {
  const used = categoriesWithObservations(categories);

  return (
    <section
      aria-label={`Summary for ${period}`}
      className="@container rounded-lg border bg-card p-4"
      aria-busy={loading || undefined}
    >
      <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {period} summary
      </h2>
      <dl className="mt-3 grid grid-cols-3 gap-2 @md:grid-cols-4 @2xl:grid-cols-7">
        {(counts ? summaryTiles(counts) : summaryTiles(EMPTY)).map((tile) => (
          <div
            key={tile.key}
            className={cn(
              "rounded-md border px-3 py-2",
              tile.key === "total" && "bg-muted/60",
            )}
          >
            <dt className="text-xs leading-tight text-muted-foreground">{tile.label}</dt>
            <dd className="text-xl font-semibold tabular-nums">
              {loading || !counts ? (
                <span className="inline-block h-6 w-8 animate-pulse rounded bg-muted align-middle" />
              ) : (
                tile.value
              )}
            </dd>
          </div>
        ))}
      </dl>
      {!loading && counts && (
        <div className="mt-3">
          <h3 className="sr-only">By category</h3>
          {used.length === 0 ? (
            <p className="text-xs text-muted-foreground">No observations recorded for {period}.</p>
          ) : (
            <ul aria-label="By category" className="flex flex-wrap gap-1.5">
              {used.map((category) => (
                <li
                  key={category.categoryId}
                  className="rounded-full border bg-background px-2.5 py-1 text-xs"
                  title={`${category.safe} safe, ${category.unsafe} unsafe`}
                >
                  {category.name}{" "}
                  <span className="font-semibold tabular-nums">{category.total}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    ({category.safe} safe · {category.unsafe} unsafe)
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

const EMPTY: ObservationCounts = {
  total: 0,
  safe: 0,
  unsafe: 0,
  safeAct: 0,
  safeCondition: 0,
  unsafeAct: 0,
  unsafeCondition: 0,
};
