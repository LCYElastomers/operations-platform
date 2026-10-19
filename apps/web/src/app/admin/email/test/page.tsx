import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { TestPage } from "@/features/notifications/test-page";

export const metadata: Metadata = { title: "Email Test Center" };

export default function Page() {
  const item = getNavItem("/admin/email/test");
  return <TestPage title={item.label} description={item.description} />;
}
