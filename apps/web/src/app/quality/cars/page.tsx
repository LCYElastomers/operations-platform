import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { carDashboardFromParams } from "@/features/quality/car/api";
import { CarDashboardPage } from "@/features/quality/car/dashboard-page";

const TITLE = "Corrective Action Reports";

export const metadata: Metadata = { title: TITLE };

export default async function QualityCarDashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/quality/cars");
  const initial = carDashboardFromParams(await searchParams);
  return <CarDashboardPage title={TITLE} description={item.description} initial={initial} />;
}
