import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { IncidentDataEntry } from "@/features/safety/incidents/incident-data-entry";

export const metadata: Metadata = { title: "Incident & Near Miss Data Entry" };

export default function IncidentDataEntryPage() {
  const item = getNavItem("/safety/incidents/data-entry");

  return <IncidentDataEntry title={item.label} description={item.description} />;
}
