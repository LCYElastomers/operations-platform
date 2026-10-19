import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { TemplatesPage } from "@/features/notifications/templates-page";

export const metadata: Metadata = { title: "Email Templates" };

export default function Page() {
  const item = getNavItem("/admin/email/templates");
  return <TemplatesPage title={item.label} description={item.description} />;
}
