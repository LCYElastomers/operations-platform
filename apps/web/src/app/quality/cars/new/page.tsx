import type { Metadata } from "next";

import { CarRecordPage } from "@/features/quality/car/car-record-page";

export const metadata: Metadata = { title: "New CAR" };

export default function NewCarPage() {
  return <CarRecordPage id={null} />;
}
