import { ArrowRight, ShieldAlert } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/common/page-header";
import { Permitted } from "@/components/layout/permitted";
import { moduleItems } from "@/config/navigation";
import { pageRequirements } from "@/lib/navigation";

export const metadata: Metadata = { title: "Safety" };

const safety = moduleItems.find((item) => item.id === "safety")!;
const areas = (safety.children ?? []).filter((child) => child.children);

export default function SafetyOverviewPage() {
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Module" title="Safety" description={safety.description} />

      {areas.map((area) => {
        const AreaIcon = area.icon ?? ShieldAlert;
        return (
          <Permitted key={area.id} anyOf={pageRequirements(area)}>
            <section
              aria-labelledby={`${area.id}-heading`}
              className="overflow-hidden rounded-lg border bg-card shadow-xs"
            >
              <div className="flex items-start gap-4 border-b px-5 py-4">
                <div className="grid size-10 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
                  <AreaIcon className="size-5" />
                </div>
                <div className="min-w-0">
                  <h2 id={`${area.id}-heading`} className="text-base font-semibold">
                    {area.label}
                  </h2>
                  {area.description && (
                    <p className="text-sm text-muted-foreground">{area.description}</p>
                  )}
                </div>
              </div>
              <ul className="grid grid-cols-1 divide-y sm:grid-cols-2 sm:divide-x sm:divide-y-0">
                {area.children?.map((page) => {
                  const Icon = page.icon;
                  return (
                    <Permitted key={page.id} anyOf={pageRequirements(page)}>
                      <li>
                        <Link
                          href={page.href!}
                          className="group flex h-full items-center gap-4 px-5 py-6 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
                        >
                          {Icon && (
                            <div className="grid size-11 shrink-0 place-items-center rounded-lg border bg-background text-primary shadow-xs group-hover:border-primary/40">
                              <Icon className="size-5" />
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="text-base font-semibold">{page.label}</p>
                            <p className="text-sm text-muted-foreground">{page.description}</p>
                          </div>
                          <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                        </Link>
                      </li>
                    </Permitted>
                  );
                })}
              </ul>
            </section>
          </Permitted>
        );
      })}

      <p className="px-1 text-xs text-muted-foreground">
        Further Safety functions will appear here as they are added to the platform.
      </p>
    </div>
  );
}
