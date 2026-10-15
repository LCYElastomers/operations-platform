"use client";

import Link from "next/link";

import { ExportMenu } from "@/components/common/export-menu";
import { PageHeader } from "@/components/common/page-header";

import { actionExportFilters, EMPTY_ACTION_QUERY, EMPTY_REGISTER_QUERY, registerExportFilters } from "./api";
import { EYEBROW } from "./psm-shared";

const REPORTS = [
  {
    key: "psm-recommendations",
    title: "PHA recommendations",
    description:
      "One row per recommendation with its disposition and action, and a separate Scenarios sheet with one row per hazard scenario (event, cause, consequence, risk).",
    filters: () => registerExportFilters(EMPTY_REGISTER_QUERY),
    filteredHref: "/safety/psm/pha",
  },
  {
    key: "psm-actions",
    title: "PSM action items",
    description: "One row per action: recommendation, governing risk, department, owner, due date, status, age, closure and verification.",
    filters: () => actionExportFilters(EMPTY_ACTION_QUERY),
    filteredHref: "/safety/psm/actions",
  },
] as const;

/** Workbook exports of every official record. Filtered exports are on the list pages. */
export function PsmReportsPage({ title, description }: { title: string; description?: string }) {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow={EYEBROW} title={title} description={description} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {REPORTS.map((report) => (
          <section key={report.key} className="flex flex-col justify-between gap-4 rounded-lg border bg-card p-4 sm:p-5">
            <div className="space-y-1">
              <h2 className="text-base font-semibold">{report.title}</h2>
              <p className="text-sm text-muted-foreground">{report.description}</p>
              <p className="text-sm text-muted-foreground">
                To export a filtered selection, filter the{" "}
                <Link href={report.filteredHref} className="text-primary hover:underline">
                  list
                </Link>{" "}
                and export from there.
              </p>
            </div>
            <div>
              <ExportMenu
                reportKey={report.key}
                title={report.title}
                formats={["xlsx"]}
                requires={["psm.view", "psm.export"]}
                context={() => ({ period: { mode: "all" }, filters: report.filters() })}
              />
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
