import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { CoqMatrixPage } from "@/features/quality/cost/matrix-page";

const TITLE = "Cost of Quality Matrix";

export const metadata: Metadata = { title: TITLE };

export default function CostOfQualityMatrixPage() {
  const item = getNavItem("/quality/cost/matrix");
  return <CoqMatrixPage title={TITLE} description={item.description} />;
}
