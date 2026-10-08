import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { PerformanceDashboard } from "@/features/safety/performance/performance-dashboard";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Safety Performance Dashboard" };

export default async function PerformanceDashboardPage() {
  // Rendered per request: the default reporting year is the Baytown year now, not at build time.
  await connection();
  const item = getNavItem("/safety/performance/dashboard");

  return <PerformanceDashboard title={item.label} description={item.description} siteToday={siteToday()} />;
}
