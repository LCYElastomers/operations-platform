import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { SettingsPage } from "@/features/notifications/settings-page";

export const metadata: Metadata = { title: "Email Settings" };

export default function Page() {
  const item = getNavItem("/admin/email/settings");
  return <SettingsPage title={item.label} description={item.description} />;
}
