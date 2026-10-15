import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { PsmSettingsPage } from "@/features/safety/psm/settings-page";

const TITLE = "PSM Settings";

export const metadata: Metadata = { title: TITLE };

export default function PsmSettingsRoute() {
  const item = getNavItem("/safety/psm/settings");
  return <PsmSettingsPage title={TITLE} description={item.description} />;
}
