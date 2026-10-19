import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { WorkflowsPage } from "@/features/notifications/workflows-page";

export const metadata: Metadata = { title: "Email Workflows" };

export default function Page() {
  const item = getNavItem("/admin/email/workflows");
  return <WorkflowsPage title={item.label} description={item.description} />;
}
