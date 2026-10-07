import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { PerformanceDataEntry } from "@/features/safety/performance/performance-data-entry";

export const metadata: Metadata = { title: "Safety Performance Data Entry" };

export default function PerformanceDataEntryPage() {
  const item = getNavItem("/safety/performance/data-entry");

  return <PerformanceDataEntry title={item.label} description={item.description} />;
}
