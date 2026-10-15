import type { Metadata } from "next";

import { NewRecommendationPage } from "@/features/safety/psm/recommendation-form";

export const metadata: Metadata = { title: "New PHA Recommendation" };

export default async function PsmNewRecommendationPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { studyId } = await searchParams;
  const initial = typeof studyId === "string" && /^[1-9]\d{0,8}$/.test(studyId) ? studyId : "";
  return <NewRecommendationPage initialStudyId={initial} />;
}
