import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { costRegisterFromRecord } from "@/features/quality/cost/cost-query";
import { CostRegisterPage } from "@/features/quality/cost/register-page";

const TITLE = "Quality Cost Register";

export const metadata: Metadata = { title: TITLE };

export default async function QualityCostRegisterPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/quality/cost/register");
  const initial = costRegisterFromRecord(await searchParams);
  return <CostRegisterPage title={TITLE} description={item.description} initial={initial} />;
}
