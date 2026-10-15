import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { PsmAuditsPage } from "@/features/safety/psm/audits-page";

const TITLE = "PSM Audits";

export const metadata: Metadata = { title: TITLE };

export default function PsmAuditsRoute() {
  const item = getNavItem("/safety/psm/audits");
  return <PsmAuditsPage title={TITLE} description={item.description} />;
}
