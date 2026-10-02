import type { Metadata } from "next";

import { ModuleNotConfigured } from "@/components/modules/module-not-configured";

export const metadata: Metadata = { title: "Environmental" };

export default function EnvironmentalPage() {
  return <ModuleNotConfigured href="/environmental" />;
}
