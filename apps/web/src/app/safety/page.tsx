import { ChevronRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { moduleItems } from "@/config/navigation";

export const metadata: Metadata = { title: "Safety" };

const safety = moduleItems.find((item) => item.id === "safety")!;
const areas = (safety.children ?? []).filter((child) => child.children);

const plannedFunctions = [
  { label: "Safety Observations", detail: "Data entry and dashboard" },
  { label: "Supervisor Safety Contacts", detail: "Data entry and dashboard" },
  { label: "Performance Rates", detail: "Dashboard" },
];

export default function SafetyOverviewPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Module"
        title="Safety"
        description={safety.description}
        status={<StatusBadge tone="info">In development</StatusBadge>}
      />

      {areas.map((area) => (
        <section key={area.id} aria-labelledby={`${area.id}-heading`} className="space-y-3">
          <div>
            <h2 id={`${area.id}-heading`} className="text-sm font-semibold text-muted-foreground">
              {area.label}
            </h2>
            {area.description && (
              <p className="text-sm text-muted-foreground">{area.description}</p>
            )}
          </div>
          <ul className="divide-y rounded-lg border bg-card">
            {area.children?.map((page) => {
              const Icon = page.icon;
              return (
                <li key={page.id}>
                  <Link
                    href={page.href!}
                    className="group flex items-center gap-4 px-4 py-4 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
                  >
                    <div className="grid size-9 shrink-0 place-items-center rounded-md border bg-muted">
                      {Icon && <Icon className="size-4 text-foreground/70" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{page.label}</p>
                      <p className="truncate text-sm text-muted-foreground">{page.description}</p>
                    </div>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      <section aria-labelledby="safety-planned-heading" className="space-y-3">
        <h2 id="safety-planned-heading" className="text-sm font-semibold text-muted-foreground">
          Planned
        </h2>
        <ul className="divide-y rounded-lg border bg-card">
          {plannedFunctions.map((item) => (
            <li key={item.label} className="flex items-center gap-4 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{item.label}</p>
                <p className="text-xs text-muted-foreground">{item.detail}</p>
              </div>
              <StatusBadge>Not configured</StatusBadge>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
