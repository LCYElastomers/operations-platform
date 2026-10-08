import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { ObservationDashboard } from "@/features/safety/observations/observation-dashboard";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Safety Observations Dashboard" };

export default async function SafetyObservationsDashboardPage() {
  // Rendered per request: the default reporting year is the Baytown year now, not at build time.
  await connection();
  const item = getNavItem("/safety/observations/dashboard");

  return (
    <ObservationDashboard
      title="Safety Observations Dashboard"
      description={item.description}
      siteToday={siteToday()}
    />
  );
}
