import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { CarDashboardPage } from "@/features/quality/car/dashboard-page";

const TITLE = "Corrective Action Reports";

export const metadata: Metadata = { title: TITLE };

export default function QualityCarDashboardPage() {
  const item = getNavItem("/quality/cars");
  return <CarDashboardPage title={TITLE} description={item.description} />;
}
