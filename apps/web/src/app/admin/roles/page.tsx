import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { RolesPage } from "@/features/admin/roles-page";

export const metadata: Metadata = { title: "Roles & Permissions" };

export default function Page() {
  const item = getNavItem("/admin/roles");
  return <RolesPage title={item.label} description={item.description} />;
}
