import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { PsmReportsPage } from "@/features/safety/psm/reports-page";

const TITLE = "PSM Reports";

export const metadata: Metadata = { title: TITLE };

export default function PsmReportsRoute() {
  const item = getNavItem("/safety/psm/reports");
  return <PsmReportsPage title={TITLE} description={item.description} />;
}
