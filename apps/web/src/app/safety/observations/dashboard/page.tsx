import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { ObservationDashboard } from "@/features/safety/observations/observation-dashboard";

export const metadata: Metadata = { title: "Safety Observations Dashboard" };

export default function SafetyObservationsDashboardPage() {
  const item = getNavItem("/safety/observations/dashboard");

  return <ObservationDashboard title="Safety Observations Dashboard" description={item.description} />;
}
