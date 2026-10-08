import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { IncidentDashboard } from "@/features/safety/incidents/incident-dashboard";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Incident & Near Miss Dashboard" };

export default async function IncidentDashboardPage() {
  // Rendered per request: the default reporting year is the Baytown year now, not at build time.
  await connection();
  const item = getNavItem("/safety/incidents/dashboard");

  return <IncidentDashboard title={item.label} description={item.description} siteToday={siteToday()} />;
}
