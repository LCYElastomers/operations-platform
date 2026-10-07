import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { ContactsPage } from "@/features/safety/contacts/contacts-page";

export const metadata: Metadata = { title: "Supervisor Safety Contacts" };

export default function SupervisorSafetyContactsPage() {
  const item = getNavItem("/safety/contacts");

  return <ContactsPage title="Supervisor Safety Contacts" description={item.description} />;
}
