import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { CopqPage } from "@/features/quality/cost/copq-page";

const TITLE = "Cost of Poor Quality";

export const metadata: Metadata = { title: TITLE };

export default function CostOfPoorQualityPage() {
  const item = getNavItem("/quality/cost/copq");
  return <CopqPage title={TITLE} description={item.description} />;
}
