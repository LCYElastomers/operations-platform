"use client";

import {
  createSortedRowModel,
  rowSortingFeature,
  sortFns,
  tableFeatures,
  useTable,
  type ColumnDef,
  type RowData,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { cn } from "@/lib/utils";

import { EmptyState } from "./empty-state";

const dataTableFeatures = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns,
});

export type DataTableColumn<TData extends RowData> = ColumnDef<typeof dataTableFeatures, TData>;

const defaultColumn = {
  // Null/undefined render as an explicit "no value" marker; zero renders as 0.
  cell: ({ getValue }: { getValue: () => unknown }) => {
    const value = getValue();
    if (value === null || value === undefined) {
      return <span className="text-muted-foreground/60">—</span>;
    }
    return String(value);
  },
};

type DataTableProps<TData extends RowData> = {
  columns: DataTableColumn<TData>[];
  data: TData[];
  /** Shown in place of rows when data is empty. */
  emptyState?: React.ReactNode;
  /** Renders placeholder rows instead of data or the empty state. */
  loading?: boolean;
  /** Allow column-header sorting. Disable when row order is meaningful. */
  enableSorting?: boolean;
  caption?: string;
  className?: string;
};

const LOADING_ROWS = 5;

export function DataTable<TData extends RowData>({
  columns,
  data,
  emptyState,
  loading = false,
  enableSorting = true,
  caption,
  className,
}: DataTableProps<TData>) {
  const table = useTable({
    features: dataTableFeatures,
    columns,
    data,
    defaultColumn,
    enableSorting,
  });

  const rows = table.getRowModel().rows;
  const columnCount = table.getAllLeafColumns().length;

  return (
    <div className={cn("overflow-hidden rounded-lg border bg-card", className)}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="bg-muted/60">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="border-b">
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  const canSort = header.column.getCanSort() && rows.length > 0;
                  const SortIcon =
                    sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;

                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={
                        sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined
                      }
                      className="h-10 px-4 text-left text-xs font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase"
                    >
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="-mx-1 inline-flex items-center gap-1 rounded px-1 hover:text-foreground"
                        >
                          <table.FlexRender header={header} />
                          <SortIcon
                            aria-hidden
                            className={cn("size-3.5", !sorted && "opacity-40")}
                          />
                        </button>
                      ) : (
                        <table.FlexRender header={header} />
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody aria-busy={loading || undefined}>
            {loading ? (
              Array.from({ length: LOADING_ROWS }, (_, index) => (
                <tr key={index} className="border-b last:border-b-0">
                  {Array.from({ length: columnCount }, (_, cell) => (
                    <td key={cell} className="h-11 px-4">
                      <div className="h-3 w-full max-w-24 animate-pulse rounded bg-muted" />
                    </td>
                  ))}
                </tr>
              ))
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columnCount} className="p-0">
                  {emptyState ?? <EmptyState variant="plain" title="No records" />}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id} className="border-b last:border-b-0 hover:bg-muted/40">
                  {row.getAllCells().map((cell) => (
                    <td key={cell.id} className="h-11 px-4 whitespace-nowrap tabular-nums">
                      <table.FlexRender cell={cell} />
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
