import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { IncidentDashboard } from "@/features/safety/incidents/incident-dashboard";

export const metadata: Metadata = { title: "Incident & Near Miss Dashboard" };

export default function IncidentDashboardPage() {
  const item = getNavItem("/safety/incidents/dashboard");

  return <IncidentDashboard title={item.label} description={item.description} />;
}
