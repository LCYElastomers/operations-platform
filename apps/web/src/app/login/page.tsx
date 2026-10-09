import type { Metadata } from "next";

import { SignInForm } from "@/features/auth/sign-in-form";
import { safeNextPath } from "@/lib/api-client";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const { next } = await searchParams;
  return <SignInForm next={safeNextPath(typeof next === "string" ? next : null)} />;
}
