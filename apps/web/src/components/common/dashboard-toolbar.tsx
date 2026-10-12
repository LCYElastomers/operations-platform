import { FilterBar } from "@/components/common/filter-bar";

/**
 * The shared toolbar of dashboards and registers: [Period ▾] [filters…] … [Export ▾].
 * `period` is a PeriodFilter, `exportMenu` an ExportMenu; both optional.
 */
export function DashboardToolbar({
  period,
  children,
  actions,
  exportMenu,
}: {
  period?: React.ReactNode;
  children?: React.ReactNode;
  /** Status and reset controls shown before the export menu. */
  actions?: React.ReactNode;
  exportMenu?: React.ReactNode;
}) {
  return (
    <FilterBar
      actions={
        actions || exportMenu ? (
          <>
            {actions}
            {exportMenu}
          </>
        ) : undefined
      }
    >
      {period}
      {children}
    </FilterBar>
  );
}
