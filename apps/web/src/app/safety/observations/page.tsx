import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { ObservationsPage } from "@/features/safety/observations/observations-page";

export const metadata: Metadata = { title: "Safety Observations" };

export default function SafetyObservationsPage() {
  const item = getNavItem("/safety/observations");

  return <ObservationsPage title="Safety Observations" description={item.description} />;
}
