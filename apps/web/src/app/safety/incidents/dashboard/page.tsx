import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { parseView } from "@/features/safety/incidents/analytics-data";
import { IncidentDashboard } from "@/features/safety/incidents/incident-dashboard";
import { siteToday } from "@/features/safety/site-calendar";

const TITLE = "Incident & Near Miss Dashboard";

export const metadata: Metadata = { title: TITLE };

function parseWhole(value: string | string[] | undefined, min: number, max: number): number | undefined {
  const text = Array.isArray(value) ? value[0] : value;
  if (!text || !/^\d{1,4}$/.test(text)) return undefined;
  const number = Number(text);
  return number >= min && number <= max ? number : undefined;
}

export default async function IncidentDashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Rendered per request: the default year and month are the Baytown date now, not at build time.
  await connection();
  const item = getNavItem("/safety/incidents/dashboard");
  const { view, year, month, eventType } = await searchParams;

  return (
    <IncidentDashboard
      title={TITLE}
      description={item.description}
      siteToday={siteToday()}
      initialView={parseView(view)}
      initialYear={parseWhole(year, 2000, 2100)}
      initialRegister={{
        month: parseWhole(month, 1, 12),
        eventType: eventType === "incident" || eventType === "near_miss" ? eventType : undefined,
      }}
    />
  );
}
