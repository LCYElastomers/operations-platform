import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { MoistureDashboard } from "@/features/quality/moisture/moisture-dashboard";

export const metadata: Metadata = { title: "Moisture Analysis" };

export default function MoistureAnalysisPage() {
  const item = getNavItem("/quality/raw-materials/moisture");

  return <MoistureDashboard title={item.label} description={item.description} />;
}
