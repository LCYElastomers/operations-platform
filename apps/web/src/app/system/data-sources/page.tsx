import { Database } from "lucide-react";
import type { Metadata } from "next";

import { DataTable, type DataTableColumn } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { getNavItem } from "@/config/navigation";

export const metadata: Metadata = { title: "Data Sources" };

type DataSourceRow = {
  name: string;
  type: string;
  module: string;
  status: string;
  lastSuccessfulSync: string | null;
};

const columns: DataTableColumn<DataSourceRow>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "type", header: "Type" },
  { accessorKey: "module", header: "Module" },
  { accessorKey: "status", header: "Status" },
  { accessorKey: "lastSuccessfulSync", header: "Last successful sync" },
];

const NO_SOURCES: DataSourceRow[] = [];

export default function DataSourcesPage() {
  const item = getNavItem("/system/data-sources");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title={item.label}
        description={item.description}
        status={<StatusBadge>Not configured</StatusBadge>}
      />
      <DataTable
        caption="Data sources"
        columns={columns}
        data={NO_SOURCES}
        emptyState={
          <EmptyState
            variant="plain"
            icon={Database}
            title="No data sources configured"
            description="Source system connections will be registered here. Credentials are stored server-side only and are never shown in the browser."
          />
        }
      />
    </div>
  );
}
