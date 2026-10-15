import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { RecommendationPage } from "@/features/safety/psm/recommendation-page";

export const metadata: Metadata = { title: "PHA Recommendation" };

export default async function PsmRecommendationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[1-9]\d{0,8}$/.test(id)) notFound();
  return <RecommendationPage id={Number(id)} />;
}
