import { ScrollText } from "lucide-react";
import type { Metadata } from "next";

import { DataTable, type DataTableColumn } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { getNavItem } from "@/config/navigation";

export const metadata: Metadata = { title: "Audit Log" };

type AuditEventRow = {
  occurredAt: string;
  actor: string | null;
  event: string;
  target: string | null;
  outcome: string;
};

const columns: DataTableColumn<AuditEventRow>[] = [
  { accessorKey: "occurredAt", header: "Time" },
  { accessorKey: "actor", header: "Actor" },
  { accessorKey: "event", header: "Event" },
  { accessorKey: "target", header: "Target" },
  { accessorKey: "outcome", header: "Outcome" },
];

const NO_EVENTS: AuditEventRow[] = [];

export default function AuditLogPage() {
  const item = getNavItem("/system/audit");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title={item.label}
        description={item.description}
        status={<StatusBadge>Not enabled</StatusBadge>}
      />
      <DataTable
        caption="Audit events"
        columns={columns}
        data={NO_EVENTS}
        emptyState={
          <EmptyState
            variant="plain"
            icon={ScrollText}
            title="No audit events"
            description="Security-relevant and ingestion events will be recorded here once authentication and data synchronization are enabled."
          />
        }
      />
    </div>
  );
}
