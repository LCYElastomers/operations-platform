import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { AuditPage } from "@/features/admin/audit-page";

export const metadata: Metadata = { title: "Audit Log" };

export default function AuditLogPage() {
  const item = getNavItem("/system/audit");
  return <AuditPage title={item.label} description={item.description} />;
}
