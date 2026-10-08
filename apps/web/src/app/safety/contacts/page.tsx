import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { ContactsPage } from "@/features/safety/contacts/contacts-page";
import { siteToday } from "@/features/safety/site-calendar";

export const metadata: Metadata = { title: "Supervisor Safety Contacts" };

export default async function SupervisorSafetyContactsPage() {
  // Rendered per request: "today" is the Baytown date now, not at build time.
  await connection();
  const item = getNavItem("/safety/contacts");

  return (
    <ContactsPage title="Supervisor Safety Contacts" description={item.description} siteToday={siteToday()} />
  );
}
