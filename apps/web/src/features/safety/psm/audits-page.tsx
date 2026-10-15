"use client";

import { ClipboardCheck } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";

import { EYEBROW } from "./psm-shared";

export function PsmAuditsPage({ title, description }: { title: string; description?: string }) {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow={EYEBROW} title={title} description={description} />
      <EmptyState
        icon={ClipboardCheck}
        title="PSM audits are not set up yet"
        description="Compliance audits of the PSM elements will be recorded here. No audit data exists yet, so nothing is shown."
      />
    </div>
  );
}
