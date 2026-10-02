import type { Metadata } from "next";

import { ModuleNotConfigured } from "@/components/modules/module-not-configured";

export const metadata: Metadata = { title: "Procurement" };

export default function ProcurementPage() {
  return <ModuleNotConfigured href="/procurement" />;
}
