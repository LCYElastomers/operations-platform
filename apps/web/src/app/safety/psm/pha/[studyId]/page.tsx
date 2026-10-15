import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { registerFromParams } from "@/features/safety/psm/api";
import { StudyPage } from "@/features/safety/psm/study-page";

export const metadata: Metadata = { title: "PHA Study" };

export default async function PsmStudyPage({
  params,
  searchParams,
}: {
  params: Promise<{ studyId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { studyId } = await params;
  if (!/^[1-9]\d{0,8}$/.test(studyId)) notFound();
  const initial = { ...registerFromParams(await searchParams), studyId };
  return <StudyPage id={Number(studyId)} initial={initial} />;
}
