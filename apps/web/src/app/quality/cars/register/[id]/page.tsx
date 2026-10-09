import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CarRecordPage } from "@/features/quality/car/car-record-page";

export const metadata: Metadata = { title: "Corrective Action Report" };

export default async function CarPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[1-9]\d{0,8}$/.test(id)) notFound();
  return <CarRecordPage id={Number(id)} />;
}
