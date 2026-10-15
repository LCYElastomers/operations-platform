import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ActionPage } from "@/features/safety/psm/action-page";

export const metadata: Metadata = { title: "PSM Action" };

export default async function PsmActionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[1-9]\d{0,8}$/.test(id)) notFound();
  return <ActionPage id={Number(id)} />;
}
