import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { PerformanceDashboard } from "@/features/safety/performance/performance-dashboard";

export const metadata: Metadata = { title: "Safety Performance Dashboard" };

export default function PerformanceDashboardPage() {
  const item = getNavItem("/safety/performance/dashboard");

  return <PerformanceDashboard title={item.label} description={item.description} />;
}
