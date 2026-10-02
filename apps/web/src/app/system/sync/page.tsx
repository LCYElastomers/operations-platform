import { RefreshCw } from "lucide-react";
import type { Metadata } from "next";

import { DataTable, type DataTableColumn } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { ApiStatusCard } from "@/components/system/api-status";
import { getNavItem } from "@/config/navigation";

export const metadata: Metadata = { title: "Sync Status" };

type SyncJobRow = {
  job: string;
  source: string;
  lastRun: string | null;
  durationSeconds: number | null;
  recordsProcessed: number | null;
  status: string;
};

const columns: DataTableColumn<SyncJobRow>[] = [
  { accessorKey: "job", header: "Job" },
  { accessorKey: "source", header: "Source" },
  { accessorKey: "lastRun", header: "Last run" },
  { accessorKey: "durationSeconds", header: "Duration (s)" },
  { accessorKey: "recordsProcessed", header: "Records" },
  { accessorKey: "status", header: "Status" },
];

const NO_JOBS: SyncJobRow[] = [];

export default function SyncStatusPage() {
  const item = getNavItem("/system/sync");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title={item.label}
        description={item.description}
        status={<StatusBadge>Not configured</StatusBadge>}
      />

      <section aria-labelledby="services-heading" className="space-y-3">
        <h2 id="services-heading" className="text-sm font-semibold text-muted-foreground">
          Services
        </h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <ApiStatusCard />
        </div>
      </section>

      <section aria-labelledby="jobs-heading" className="space-y-3">
        <h2 id="jobs-heading" className="text-sm font-semibold text-muted-foreground">
          Synchronization jobs
        </h2>
        <DataTable
          caption="Synchronization jobs"
          columns={columns}
          data={NO_JOBS}
          emptyState={
            <EmptyState
              variant="plain"
              icon={RefreshCw}
              title="No synchronization jobs"
              description="Jobs will be listed here once a data source is configured."
            />
          }
        />
      </section>
    </div>
  );
}
