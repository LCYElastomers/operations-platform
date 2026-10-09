import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { AssignmentsPage } from "@/features/assignments/assignments-page";

export const metadata: Metadata = { title: "My Assignments" };

export default function Page() {
  const item = getNavItem("/my-assignments");
  return <AssignmentsPage title={item.label} description={item.description} />;
}
