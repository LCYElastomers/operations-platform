import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { CostRegisterPage } from "@/features/quality/cost/register-page";

const TITLE = "Quality Cost Register";

export const metadata: Metadata = { title: TITLE };

export default function QualityCostRegisterPage() {
  const item = getNavItem("/quality/cost/register");
  return <CostRegisterPage title={TITLE} description={item.description} />;
}
