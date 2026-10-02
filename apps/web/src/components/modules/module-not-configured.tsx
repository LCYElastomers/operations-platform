import { ArrowRight, Settings2 } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { buttonVariants } from "@/components/ui/button";
import { getNavItem } from "@/config/navigation";

const setupSteps = [
  { title: "Connect a data source", detail: "Register the source system that feeds this module." },
  { title: "Configure synchronization", detail: "Schedule ingestion and validate imported records." },
  { title: "Enable module views", detail: "Publish dashboards once real data is flowing." },
];

/** Standard page for modules that exist in navigation but have no data yet. */
export function ModuleNotConfigured({ href }: { href: string }) {
  const item = getNavItem(href);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Module"
        title={item.label}
        description={item.description}
        status={<StatusBadge>Not configured</StatusBadge>}
      />

      <EmptyState
        icon={item.icon ?? Settings2}
        title={`${item.label} is not configured`}
        description="No data source is connected to this module. Dashboards will appear here once a source is configured and synchronized. No sample or placeholder data is shown."
        action={
          <Link href="/system/data-sources" className={buttonVariants({ variant: "outline" })}>
            View data sources
            <ArrowRight />
          </Link>
        }
      />

      <section aria-labelledby="setup-heading" className="rounded-lg border bg-card">
        <h2 id="setup-heading" className="border-b px-4 py-3 text-sm font-semibold">
          Setup checklist
        </h2>
        <ol className="divide-y">
          {setupSteps.map((step, index) => (
            <li key={step.title} className="flex items-center gap-4 px-4 py-3">
              <span className="grid size-6 shrink-0 place-items-center rounded-full border text-xs font-medium text-muted-foreground tabular-nums">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{step.title}</p>
                <p className="text-xs text-muted-foreground">{step.detail}</p>
              </div>
              <StatusBadge tone="pending">Pending</StatusBadge>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
