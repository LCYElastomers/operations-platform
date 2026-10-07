"use client";

import { useRef } from "react";

import { cn } from "@/lib/utils";

export type MonthlyGridCell = {
  /** Raw input text. Empty means "not reported", which is distinct from "0". */
  text: string;
  /** Changed from the stored value and not yet saved. */
  dirty?: boolean;
  invalid?: boolean;
};

export type MonthlyGridRow = {
  id: string;
  label: string;
  cells: MonthlyGridCell[];
  /** Calculated, read-only row total; null when no month is reported. */
  total: number | null;
};

type MonthlyGridProps = {
  title: string;
  /** Column labels, one per editable period (e.g. Jan..Dec). */
  columns: string[];
  rows: MonthlyGridRow[];
  totalLabel?: string;
  /** Calculated per-column totals across rows, shown as a read-only footer. */
  footer?: { label: string; values: (number | null)[]; total: number | null };
  editable: boolean;
  onCellChange?: (rowId: string, column: number, text: string) => void;
  /** Escape restores the stored value of a cell. */
  onCellRevert?: (rowId: string, column: number) => void;
  loading?: boolean;
  className?: string;
};

const LOADING_ROWS = 3;
const GRID_LINE = "border-l border-border/60";
// Shadows, not borders: collapsed table borders do not stay with sticky cells.
const STICKY_EDGE = "shadow-[inset_-1px_0_0_var(--color-border)]";
const STICKY_TOTAL = "sticky right-0 z-10 shadow-[inset_1px_0_0_var(--color-border)]";

function NoValue() {
  return (
    <>
      <span aria-hidden className="text-muted-foreground/50">
        —
      </span>
      <span className="sr-only">Not reported</span>
    </>
  );
}

function formatTotal(value: number | null) {
  return value === null ? <NoValue /> : value.toLocaleString();
}

/**
 * Spreadsheet-style period grid. Arrow keys, Enter and Shift+Enter move
 * between cells; focusing a cell selects its contents so typing replaces it.
 */
export function MonthlyGrid({
  title,
  columns,
  rows,
  totalLabel = "YTD",
  footer,
  editable,
  onCellChange,
  onCellRevert,
  loading = false,
  className,
}: MonthlyGridProps) {
  const tableRef = useRef<HTMLTableElement>(null);
  const headingId = `grid-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  const focusCell = (row: number, column: number) => {
    const target = tableRef.current?.querySelector<HTMLInputElement>(
      `input[data-cell="${row}:${column}"]`,
    );
    if (!target) return false;
    target.focus();
    target.select();
    return true;
  };

  const handleKeyDown = (
    event: React.KeyboardEvent<HTMLInputElement>,
    rowIndex: number,
    column: number,
    rowId: string,
  ) => {
    const input = event.currentTarget;
    const atStart = input.selectionStart === 0 && input.selectionEnd === 0;
    const atEnd =
      input.selectionStart === input.value.length && input.selectionEnd === input.value.length;
    const allSelected =
      input.selectionStart === 0 && input.selectionEnd === input.value.length;
    let moved = false;
    switch (event.key) {
      case "ArrowUp":
        moved = focusCell(rowIndex - 1, column);
        break;
      case "ArrowDown":
        moved = focusCell(rowIndex + 1, column);
        break;
      case "Enter":
        moved = focusCell(event.shiftKey ? rowIndex - 1 : rowIndex + 1, column);
        break;
      case "ArrowLeft":
        if (atStart || allSelected) moved = focusCell(rowIndex, column - 1);
        break;
      case "ArrowRight":
        if (atEnd || allSelected) moved = focusCell(rowIndex, column + 1);
        break;
      case "Escape":
        onCellRevert?.(rowId, column);
        moved = true;
        break;
    }
    if (moved) event.preventDefault();
  };

  return (
    <section
      aria-labelledby={headingId}
      className={cn("overflow-hidden rounded-lg border bg-card", className)}
    >
      <h2 id={headingId} className="border-b bg-muted/40 px-4 py-2.5 text-sm font-semibold">
        {title}
      </h2>
      {/* relative: keeps absolutely positioned screen-reader text inside the scroll area. */}
      <div className="relative overflow-x-auto">
        <table ref={tableRef} className="w-full min-w-[1040px] table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-56" />
            {columns.map((column) => (
              <col key={column} />
            ))}
            <col className="w-20" />
          </colgroup>
          <thead className="bg-muted/60">
            <tr className="border-b">
              <th
                scope="col"
                className={cn(
                  "sticky left-0 z-10 h-9 bg-muted px-4 text-left text-xs font-semibold tracking-wide text-muted-foreground uppercase",
                  STICKY_EDGE,
                )}
              >
                Category
              </th>
              {columns.map((column, index) => (
                <th
                  key={column}
                  scope="col"
                  className={cn(
                    "h-9 px-2.5 text-right text-xs font-semibold tracking-wide text-muted-foreground uppercase",
                    index > 0 && GRID_LINE,
                  )}
                >
                  {column}
                </th>
              ))}
              <th
                scope="col"
                title="Calculated from the monthly values; not editable"
                className={cn(
                  "h-9 bg-muted px-3 text-right text-xs font-semibold tracking-wide text-foreground uppercase",
                  STICKY_TOTAL,
                )}
              >
                {totalLabel}
              </th>
            </tr>
          </thead>
          <tbody aria-busy={loading || undefined}>
            {loading
              ? Array.from({ length: LOADING_ROWS }, (_, index) => (
                  <tr key={index} className="border-b last:border-b-0">
                    {Array.from({ length: columns.length + 2 }, (_, cell) => (
                      <td key={cell} className="h-10 px-3">
                        <div className="h-3 w-full animate-pulse rounded bg-muted" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((row, rowIndex) => (
                  <tr key={row.id} className="border-b last:border-b-0 hover:bg-muted/30">
                    <th
                      scope="row"
                      className={cn(
                        "sticky left-0 z-10 truncate bg-card px-4 text-left font-medium",
                        STICKY_EDGE,
                      )}
                      title={row.label}
                    >
                      {row.label}
                    </th>
                    {row.cells.map((cell, column) => (
                      <td key={column} className={cn("h-10 p-0.5", column > 0 && GRID_LINE)}>
                        {editable ? (
                          <input
                            data-cell={`${rowIndex}:${column}`}
                            type="text"
                            inputMode="numeric"
                            autoComplete="off"
                            spellCheck={false}
                            maxLength={7}
                            aria-label={`${row.label}, ${columns[column]}`}
                            aria-invalid={cell.invalid || undefined}
                            placeholder="—"
                            value={cell.text}
                            onChange={(event) => onCellChange?.(row.id, column, event.target.value)}
                            onFocus={(event) => event.currentTarget.select()}
                            onKeyDown={(event) => handleKeyDown(event, rowIndex, column, row.id)}
                            className={cn(
                              "h-9 w-full rounded-sm border border-transparent bg-transparent px-2 text-right tabular-nums outline-none",
                              "placeholder:text-muted-foreground/45 hover:border-input",
                              "focus:border-ring focus:bg-background focus:ring-2 focus:ring-ring/40",
                              cell.dirty && "bg-warning/20 font-semibold",
                              cell.invalid &&
                                "border-destructive bg-destructive/10 focus:border-destructive focus:ring-destructive/30",
                            )}
                          />
                        ) : (
                          <div className="px-2 text-right tabular-nums">
                            {cell.text === "" ? <NoValue /> : cell.text}
                          </div>
                        )}
                      </td>
                    ))}
                    <td
                      className={cn(
                        "h-10 bg-muted px-3 text-right font-semibold tabular-nums",
                        STICKY_TOTAL,
                      )}
                    >
                      {formatTotal(row.total)}
                    </td>
                  </tr>
                ))}
          </tbody>
          {footer && !loading && (
            <tfoot className="border-t-2 bg-muted/40">
              <tr>
                <th
                  scope="row"
                  className={cn(
                    "sticky left-0 z-10 h-10 bg-muted px-4 text-left text-xs font-semibold tracking-wide uppercase",
                    STICKY_EDGE,
                  )}
                >
                  {footer.label}
                </th>
                {footer.values.map((value, column) => (
                  <td
                    key={column}
                    className={cn(
                      "h-10 px-2.5 text-right font-medium tabular-nums",
                      column > 0 && GRID_LINE,
                    )}
                  >
                    {formatTotal(value)}
                  </td>
                ))}
                <td
                  className={cn("h-10 bg-muted px-3 text-right font-semibold tabular-nums", STICKY_TOTAL)}
                >
                  {formatTotal(footer.total)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </section>
  );
}
