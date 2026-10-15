import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { ActionsPage } from "@/features/safety/psm/actions-page";
import { actionsFromParams } from "@/features/safety/psm/api";

const TITLE = "PSM Action Items";

export const metadata: Metadata = { title: TITLE };

export default async function PsmActionsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/safety/psm/actions");
  const initial = actionsFromParams(await searchParams);
  return <ActionsPage title={TITLE} description={item.description} initial={initial} />;
}
