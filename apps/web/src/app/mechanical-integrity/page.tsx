import type { Metadata } from "next";

import { ModuleNotConfigured } from "@/components/modules/module-not-configured";

export const metadata: Metadata = { title: "Mechanical Integrity" };

export default function MechanicalIntegrityPage() {
  return <ModuleNotConfigured href="/mechanical-integrity" />;
}
