import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { CommandCenter } from "@/features/safety/psm/command-center";

const TITLE = "PSM Command Center";

export const metadata: Metadata = { title: TITLE };

export default async function PsmCommandCenterPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/safety/psm");
  const { studyId } = await searchParams;
  const initial = typeof studyId === "string" && /^[1-9]\d{0,8}$/.test(studyId) ? studyId : "";
  return <CommandCenter title={TITLE} description={item.description} initialStudyId={initial} />;
}
