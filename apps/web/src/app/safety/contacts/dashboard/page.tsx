import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { ContactDashboard } from "@/features/safety/contacts/contact-dashboard";

export const metadata: Metadata = { title: "Supervisor Safety Contacts Dashboard" };

export default function SupervisorSafetyContactsDashboardPage() {
  const item = getNavItem("/safety/contacts/dashboard");

  return <ContactDashboard title="Supervisor Safety Contacts Dashboard" description={item.description} />;
}
