import type { Metadata } from "next";

import { getNavItem } from "@/config/navigation";
import { ProfilePage } from "@/features/auth/profile-page";

export const metadata: Metadata = { title: "Profile" };

export default function Page() {
  const item = getNavItem("/profile");
  return <ProfilePage title={item.label} description={item.description} />;
}
