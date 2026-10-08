"use client";

import { ChevronRight } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

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
  /** Shown as the row header's tooltip, e.g. a category definition. */
  description?: string | null;
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
  /** Makes the header a disclosure button. Collapsing only hides the grid; edits live with the caller. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Shown in the header while collapsed. */
  summary?: React.ReactNode;
  /** Shown in the header at all times, e.g. an unsaved-changes badge. */
  status?: React.ReactNode;
  /** Shown under the grid while it is expanded, e.g. data checks. */
  notes?: React.ReactNode;
  loading?: boolean;
  className?: string;
};

const LOADING_ROWS = 3;
const GRID_LINE = "border-l border-border/60";
// Shadows, not borders: collapsed table borders do not stay with sticky cells.
const EDGE_LINE_START = "shadow-[inset_-1px_0_0_var(--color-border)]";
const EDGE_LINE_END = "shadow-[inset_1px_0_0_var(--color-border)]";
const EDGE_FADE_START =
  "shadow-[inset_-1px_0_0_var(--color-border),8px_0_10px_-8px_rgb(15_23_42/0.28)]";
const EDGE_FADE_END =
  "shadow-[inset_1px_0_0_var(--color-border),-8px_0_10px_-8px_rgb(15_23_42/0.28)]";

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
 * Spreadsheet-style period grid. The first column and the total column stay
 * pinned while the periods scroll horizontally inside the card.
 */
export function MonthlyGrid({
  title,
  open,
  onOpenChange,
  summary,
  status,
  notes,
  className,
  ...grid
}: MonthlyGridProps) {
  const id = useId();
  const headingId = `${id}-heading`;
  const bodyId = `${id}-body`;
  const collapsible = open !== undefined;
  const expanded = open ?? true;

  return (
    <section
      aria-labelledby={headingId}
      className={cn("min-w-0 overflow-hidden rounded-lg border bg-card", className)}
    >
      <h2 className={cn("bg-muted/40 text-sm font-semibold", expanded && "border-b")}>
        {collapsible ? (
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={bodyId}
            onClick={() => onOpenChange?.(!expanded)}
            className={cn(
              "flex min-h-12 w-full items-center gap-3 px-4 py-2.5 text-left select-none pointer-coarse:min-h-14",
              "transition-colors hover:bg-muted/70",
              "focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none focus-visible:ring-inset",
            )}
          >
            <ChevronRight
              aria-hidden
              className={cn(
                "size-4 shrink-0 text-muted-foreground transition-transform",
                expanded && "rotate-90",
              )}
            />
            <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-center sm:gap-3">
              <span id={headingId} className="min-w-0 truncate sm:flex-1">
                {title}
              </span>
              {!expanded && summary && (
                <span className="truncate text-xs font-normal text-muted-foreground tabular-nums sm:max-w-[55%]">
                  {summary}
                </span>
              )}
            </span>
            {status}
          </button>
        ) : (
          <span id={headingId} className="block px-4 py-2.5">
            {title}
          </span>
        )}
      </h2>
      <div id={bodyId} hidden={!expanded}>
        {expanded && <GridTable {...grid} />}
        {expanded && notes && <div className="border-t px-4 py-2.5">{notes}</div>}
      </div>
    </section>
  );
}

type GridTableProps = Omit<
  MonthlyGridProps,
  "title" | "open" | "onOpenChange" | "summary" | "status" | "notes" | "className"
>;

function GridTable({
  columns,
  rows,
  totalLabel = "YTD",
  footer,
  editable,
  onCellChange,
  onCellRevert,
  loading = false,
}: GridTableProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const pointerFocus = useRef<HTMLInputElement | null>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  const [focusedColumn, setFocusedColumn] = useState<number | null>(null);

  const updateEdges = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    const start = element.scrollLeft > 1;
    const end = element.scrollLeft + element.clientWidth < element.scrollWidth - 1;
    setEdges((current) =>
      current.start === start && current.end === end ? current : { start, end },
    );
  }, []);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const observer = new ResizeObserver(updateEdges);
    observer.observe(element);
    return () => observer.disconnect();
  }, [updateEdges]);

  const stickyStart = cn("sticky left-0 z-10", edges.start ? EDGE_FADE_START : EDGE_LINE_START);
  const stickyEnd = cn("sticky right-0 z-10", edges.end ? EDGE_FADE_END : EDGE_LINE_END);

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

  // The first click or tap into a cell selects its value so typing replaces it;
  // the browser would otherwise place a caret after focus. A second click or
  // tap places the caret as usual.
  const handlePointerDown = (event: React.PointerEvent<HTMLInputElement>) => {
    pointerFocus.current = document.activeElement === event.currentTarget ? null : event.currentTarget;
  };
  const handleClick = (event: React.MouseEvent<HTMLInputElement>) => {
    if (pointerFocus.current !== event.currentTarget) return;
    pointerFocus.current = null;
    event.currentTarget.select();
  };

  return (
    <div
      ref={scrollRef}
      onScroll={updateEdges}
      // relative: keeps absolutely positioned screen-reader text inside the scroll area.
      // scroll padding: cells reached by keyboard are not hidden under the pinned columns.
      className="relative overflow-x-auto overscroll-x-contain scroll-pr-16 scroll-pl-32 sm:scroll-pr-20 sm:scroll-pl-40 xl:scroll-pl-48"
    >
      <table
        ref={tableRef}
        className="w-full min-w-[940px] table-fixed border-collapse text-sm select-none"
      >
        <colgroup>
          <col className="w-32 sm:w-40 xl:w-48" />
          {columns.map((column) => (
            <col key={column} />
          ))}
          <col className="w-16 sm:w-20" />
        </colgroup>
        <thead className="bg-muted/60">
          <tr className="border-b">
            <th
              scope="col"
              className={cn(
                "h-9 bg-muted px-3 text-left text-xs font-semibold tracking-wide text-muted-foreground uppercase sm:px-4",
                stickyStart,
              )}
            >
              Category
            </th>
            {columns.map((column, index) => (
              <th
                key={column}
                scope="col"
                className={cn(
                  "h-9 px-2.5 text-right text-xs font-semibold tracking-wide text-muted-foreground uppercase transition-colors",
                  index > 0 && GRID_LINE,
                  focusedColumn === index && "bg-primary/10 text-foreground",
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
                stickyEnd,
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
                <tr
                  key={row.id}
                  className="group/row border-b last:border-b-0 hover:bg-muted/30 focus-within:bg-primary/5"
                >
                  <th
                    scope="row"
                    className={cn(
                      "bg-card px-3 text-left leading-tight font-medium group-focus-within/row:text-primary sm:px-4",
                      stickyStart,
                    )}
                    title={row.description ? `${row.label}\n${row.description}` : row.label}
                  >
                    <span className="line-clamp-2">{row.label}</span>
                  </th>
                  {row.cells.map((cell, column) => (
                    <td
                      key={column}
                      className={cn("h-10 p-0.5 pointer-coarse:h-12", column > 0 && GRID_LINE)}
                    >
                      {editable ? (
                        <input
                          data-cell={`${rowIndex}:${column}`}
                          type="text"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          enterKeyHint="next"
                          autoComplete="off"
                          autoCorrect="off"
                          spellCheck={false}
                          maxLength={7}
                          aria-label={`${row.label}, ${columns[column]}`}
                          aria-invalid={cell.invalid || undefined}
                          placeholder="—"
                          value={cell.text}
                          onChange={(event) => onCellChange?.(row.id, column, event.target.value)}
                          onFocus={(event) => {
                            event.currentTarget.select();
                            setFocusedColumn(column);
                          }}
                          onBlur={() => setFocusedColumn(null)}
                          onPointerDown={handlePointerDown}
                          onClick={handleClick}
                          onKeyDown={(event) => handleKeyDown(event, rowIndex, column, row.id)}
                          className={cn(
                            // 16px text on touch devices stops iOS zooming in on focus.
                            "h-9 w-full scroll-mt-44 scroll-mb-4 rounded-sm border border-transparent bg-transparent px-2 text-right tabular-nums outline-none select-text md:scroll-mt-36",
                            "pointer-coarse:h-11 pointer-coarse:text-base",
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
                      "h-10 bg-muted px-3 text-right font-semibold tabular-nums pointer-coarse:h-12",
                      stickyEnd,
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
                  "h-10 bg-muted px-4 text-left text-xs font-semibold tracking-wide uppercase",
                  stickyStart,
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
              <td className={cn("h-10 bg-muted px-3 text-right font-semibold tabular-nums", stickyEnd)}>
                {formatTotal(footer.total)}
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
