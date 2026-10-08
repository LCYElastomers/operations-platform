import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { IncidentAnalytics } from "@/features/safety/incidents/incident-analytics";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Incident & Near Miss Analytics" };

export default async function IncidentAnalyticsPage() {
  // Rendered per request: the default year and month are the Baytown date now, not at build time.
  await connection();
  const item = getNavItem("/safety/incidents/analytics");

  return <IncidentAnalytics title={item.label} description={item.description} siteToday={siteToday()} />;
}
