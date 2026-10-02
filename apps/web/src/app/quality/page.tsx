import { ChevronRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { moduleItems } from "@/config/navigation";

export const metadata: Metadata = { title: "Quality" };

const quality = moduleItems.find((item) => item.id === "quality")!;
const areas = (quality.children ?? []).filter((child) => child.children);

export default function QualityOverviewPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Module"
        title="Quality"
        description={quality.description}
        status={<StatusBadge tone="info">In development</StatusBadge>}
      />

      {areas.map((area) => (
        <section key={area.id} aria-labelledby={`${area.id}-heading`} className="space-y-3">
          <h2 id={`${area.id}-heading`} className="text-sm font-semibold text-muted-foreground">
            {area.label}
          </h2>
          <ul className="divide-y rounded-lg border bg-card">
            {area.children?.map((analysis) => {
              const Icon = analysis.icon;
              return (
                <li key={analysis.id}>
                  <Link
                    href={analysis.href!}
                    className="group flex items-center gap-4 px-4 py-4 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
                  >
                    <div className="grid size-9 shrink-0 place-items-center rounded-md border bg-muted">
                      {Icon && <Icon className="size-4 text-foreground/70" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{analysis.label}</p>
                      <p className="truncate text-sm text-muted-foreground">
                        {analysis.description}
                      </p>
                    </div>
                    <StatusBadge tone="warning" className="hidden sm:inline-flex">
                      Development fixture
                    </StatusBadge>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
