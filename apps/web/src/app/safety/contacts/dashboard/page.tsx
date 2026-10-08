import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { ContactDashboard } from "@/features/safety/contacts/contact-dashboard";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Supervisor Safety Contacts Dashboard" };

export default async function SupervisorSafetyContactsDashboardPage() {
  // Rendered per request: the default reporting year is the Baytown year now, not at build time.
  await connection();
  const item = getNavItem("/safety/contacts/dashboard");

  return (
    <ContactDashboard
      title="Supervisor Safety Contacts Dashboard"
      description={item.description}
      siteToday={siteToday()}
    />
  );
}
