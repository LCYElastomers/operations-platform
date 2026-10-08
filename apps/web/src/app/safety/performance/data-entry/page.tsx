import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { PerformanceDataEntry } from "@/features/safety/performance/performance-data-entry";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Safety Performance Data Entry" };

export default async function PerformanceDataEntryPage() {
  // Rendered per request: the default reporting year is the Baytown year now, not at build time.
  await connection();
  const item = getNavItem("/safety/performance/data-entry");

  return <PerformanceDataEntry title={item.label} description={item.description} siteToday={siteToday()} />;
}
