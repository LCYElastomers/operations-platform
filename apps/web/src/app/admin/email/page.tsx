import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { OverviewPage } from "@/features/notifications/overview-page";

export const metadata: Metadata = { title: "Email Management" };

export default function Page() {
  const item = getNavItem("/admin/email");
  return <OverviewPage title={item.label} description={item.description} />;
}
