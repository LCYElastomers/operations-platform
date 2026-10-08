import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { IncidentDataEntry } from "@/features/safety/incidents/incident-data-entry";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Incident & Near Miss Data Entry" };

export default async function IncidentDataEntryPage() {
  // Rendered per request: the default reporting year is the Baytown year now, not at build time.
  await connection();
  const item = getNavItem("/safety/incidents/data-entry");

  return <IncidentDataEntry title={item.label} description={item.description} siteToday={siteToday()} />;
}
