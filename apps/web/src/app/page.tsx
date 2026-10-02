import { ArrowRight, Database, RefreshCw } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { ApiStatusCard } from "@/components/system/api-status";
import { moduleItems } from "@/config/navigation";
import type { ModuleStatus, NavItem } from "@/lib/navigation";

const statusDisplay: Record<ModuleStatus, { label: string; tone: StatusTone }> = {
  available: { label: "Available", tone: "success" },
  "in-development": { label: "In development", tone: "info" },
  "not-configured": { label: "Not configured", tone: "neutral" },
};

function firstHref(item: NavItem): string | undefined {
  if (item.href) return item.href;
  for (const child of item.children ?? []) {
    const href = firstHref(child);
    if (href) return href;
  }
  return undefined;
}

export default function OverviewPage() {
  return (
    <div className="space-y-8">
      <PageHeader title="Overview" description="Operational modules and platform status." />

      <section aria-labelledby="modules-heading" className="space-y-3">
        <h2 id="modules-heading" className="text-sm font-semibold text-muted-foreground">
          Modules
        </h2>
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {moduleItems.map((item) => {
            const href = firstHref(item);
            const status = statusDisplay[item.status ?? "not-configured"];
            const Icon = item.icon;
            return (
              <li key={item.id}>
                <Link
                  href={href ?? "/"}
                  className="group flex h-full flex-col rounded-lg border bg-card p-4 shadow-xs transition-colors hover:border-ring/60 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="grid size-9 place-items-center rounded-md border bg-muted">
                      {Icon && <Icon className="size-4 text-foreground/70" />}
                    </div>
                    <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                  </div>
                  <h3 className="mt-4 text-sm font-semibold">{item.label}</h3>
                  <p className="mt-1 flex-1 text-sm text-muted-foreground">{item.description}</p>
                  <span className="mt-4 inline-flex items-center gap-1 text-xs font-medium text-muted-foreground group-hover:text-foreground">
                    Open module
                    <ArrowRight className="size-3.5" />
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="platform-heading" className="space-y-3">
        <h2 id="platform-heading" className="text-sm font-semibold text-muted-foreground">
          Platform
        </h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <ApiStatusCard />
          <PlatformLink href="/system/data-sources" icon={Database} label="Data sources" />
          <PlatformLink href="/system/sync" icon={RefreshCw} label="Synchronization" />
        </div>
      </section>
    </div>
  );
}

function PlatformLink({
  href,
  icon: Icon,
  label,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between gap-4 rounded-lg border bg-card px-4 py-3 transition-colors hover:border-ring/60 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <span className="flex items-center gap-3">
        <Icon className="size-4 text-muted-foreground" />
        <span className="text-sm font-medium">{label}</span>
      </span>
      <StatusBadge>Not configured</StatusBadge>
    </Link>
  );
}
