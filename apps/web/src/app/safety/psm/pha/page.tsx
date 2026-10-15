import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { registerFromParams } from "@/features/safety/psm/api";
import { RegisterPage } from "@/features/safety/psm/register-page";

const TITLE = "PHA Management";

export const metadata: Metadata = { title: TITLE };

export default async function PsmPhaPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const item = getNavItem("/safety/psm/pha");
  const initial = registerFromParams(await searchParams);
  return <RegisterPage title={TITLE} description={item.description} initial={initial} />;
}
