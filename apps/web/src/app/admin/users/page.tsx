import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { UsersPage } from "@/features/admin/users-page";

export const metadata: Metadata = { title: "Users" };

export default function Page() {
  const item = getNavItem("/admin/users");
  return <UsersPage title={item.label} description={item.description} />;
}
