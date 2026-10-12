import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { costDashboardFromParams } from "@/features/quality/cost/cost-query";
import { CoqMatrixPage } from "@/features/quality/cost/matrix-page";

const TITLE = "Cost of Quality Matrix";

export const metadata: Metadata = { title: TITLE };

export default async function CostOfQualityMatrixPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/quality/cost/matrix");
  const initial = costDashboardFromParams(await searchParams);
  return <CoqMatrixPage title={TITLE} description={item.description} initial={initial} />;
}
