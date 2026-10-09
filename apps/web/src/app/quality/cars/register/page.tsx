import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { carQueryFromParams } from "@/features/quality/car/api";
import { CarRegisterPage } from "@/features/quality/car/register-page";

const TITLE = "CAR Register";

export const metadata: Metadata = { title: TITLE };

export default async function QualityCarRegisterPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/quality/cars/register");
  const initial = carQueryFromParams(await searchParams);
  return <CarRegisterPage title={TITLE} description={item.description} initial={initial} />;
}
