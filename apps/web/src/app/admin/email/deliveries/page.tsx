import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { DeliveriesPage } from "@/features/notifications/deliveries-page";

export const metadata: Metadata = { title: "Email Delivery Log" };

export default function Page() {
  const item = getNavItem("/admin/email/deliveries");
  return <DeliveriesPage title={item.label} description={item.description} />;
}
