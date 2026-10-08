import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { parseView } from "@/features/safety/incidents/analytics-data";
import { IncidentDashboard } from "@/features/safety/incidents/incident-dashboard";
import { siteToday } from "@/features/safety/site-calendar";

const TITLE = "Incident & Near Miss Dashboard";

export const metadata: Metadata = { title: TITLE };

export default async function IncidentDashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Rendered per request: the default year and month are the Baytown date now, not at build time.
  await connection();
  const item = getNavItem("/safety/incidents/dashboard");
  const { view } = await searchParams;

  return (
    <IncidentDashboard
      title={TITLE}
      description={item.description}
      siteToday={siteToday()}
      initialView={parseView(view)}
    />
  );
}
