import type { Metadata } from "next";

import { ModuleNotConfigured } from "@/components/modules/module-not-configured";

export const metadata: Metadata = { title: "Safety" };

export default function SafetyPage() {
  return <ModuleNotConfigured href="/safety" />;
}
