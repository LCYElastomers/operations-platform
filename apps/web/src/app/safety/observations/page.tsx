import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { ObservationsPage } from "@/features/safety/observations/observations-page";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Safety Observations" };

export default async function SafetyObservationsPage() {
  // Rendered per request: "today" is the Baytown date now, not at build time.
  await connection();
  const item = getNavItem("/safety/observations");

  return <ObservationsPage title="Safety Observations" description={item.description} siteToday={siteToday()} />;
}
