import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { parseView } from "@/features/safety/incidents/analytics-data";
import { IncidentDashboard } from "@/features/safety/incidents/incident-dashboard";
import { parseDrill } from "@/features/safety/incidents/records/insights-data";
import { siteToday } from "@/features/safety/site-calendar";

const TITLE = "Incident & Near Miss Dashboard";

export const metadata: Metadata = { title: TITLE };

function parseWhole(value: string | string[] | undefined, min: number, max: number): number | undefined {
  const text = Array.isArray(value) ? value[0] : value;
  if (!text || !/^\d{1,4}$/.test(text)) return undefined;
  const number = Number(text);
  return number >= min && number <= max ? number : undefined;
}

function parseId(value: string | string[] | undefined): number | undefined {
  const text = Array.isArray(value) ? value[0] : value;
  return text && /^[1-9]\d{0,8}$/.test(text) ? Number(text) : undefined;
}

export default async function IncidentDashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Rendered per request: the default year and month are the Baytown date now, not at build time.
  await connection();
  const item = getNavItem("/safety/incidents/dashboard");
  const params = await searchParams;
  const { view, year, month, eventType, record } = params;

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
        areaId: parseId(params.areaId),
        classificationId: parseId(params.classificationId),
        record: parseId(record),
        ...parseDrill(params),
      }}
    />
  );
}
