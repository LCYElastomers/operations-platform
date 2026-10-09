import type { Metadata } from "next";

import { SetupPasswordForm } from "@/features/auth/setup-password-form";

export const metadata: Metadata = { title: "Set your password", referrer: "no-referrer" };

export default function SetupPasswordPage() {
  return <SetupPasswordForm />;
}
