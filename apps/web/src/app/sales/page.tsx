import type { Metadata } from "next";

import { ModuleNotConfigured } from "@/components/modules/module-not-configured";

export const metadata: Metadata = { title: "Sales" };

export default function SalesPage() {
  return <ModuleNotConfigured href="/sales" />;
}
