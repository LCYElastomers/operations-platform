import type { Metadata } from "next";
import { connection } from "next/server";

import { getNavItem } from "@/config/navigation";
import { siteToday } from "@/features/safety/site-calendar";
import { TrirExperiencePage } from "@/features/safety/trir/trir-experience";

const TITLE = "TRIR Experience";

export const metadata: Metadata = { title: TITLE };

export default async function TrirPage() {
  // Rendered per request: the default year is the Baytown date now, not at build time.
  await connection();
  const item = getNavItem("/safety/trir");
  return <TrirExperiencePage title={TITLE} description={item.description} siteToday={siteToday()} />;
}
