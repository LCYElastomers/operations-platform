import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { CopqPage } from "@/features/quality/cost/copq-page";
import { costDashboardFromParams } from "@/features/quality/cost/cost-query";

const TITLE = "Cost of Poor Quality";

export const metadata: Metadata = { title: TITLE };

export default async function CostOfPoorQualityPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/quality/cost/copq");
  const initial = costDashboardFromParams(await searchParams);
  return <CopqPage title={TITLE} description={item.description} initial={initial} />;
}
