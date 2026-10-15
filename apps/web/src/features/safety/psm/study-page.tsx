"use client";

import { ArrowLeft, Pencil } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { formatDate } from "@/features/quality/cost/format";

import type { RegisterQuery } from "./api";
import { Detail, EYEBROW, PsmError } from "./psm-shared";
import { NewRecommendationLink, RegisterPage } from "./register-page";
import { StudyDialog } from "./study-dialog";
import { usePsmOptions, useStudy } from "./use-psm";

export function StudyPage({ id, initial }: { id: number; initial: RegisterQuery }) {
  const study = useStudy(id);
  const options = usePsmOptions();
  const [editing, setEditing] = useState(false);
  const back = (
    <Link href="/safety/psm/pha" className={buttonVariants({ variant: "ghost", size: "sm" })}>
      <ArrowLeft />
      PHA Management
    </Link>
  );
  if (study.isError) {
    return (
      <div className="space-y-5">
        {back}
        <PsmError error={study.error} onRetry={() => void study.refetch()} />
      </div>
    );
  }
  if (!study.data) return <p className="py-6 text-sm text-muted-foreground">Loading study…</p>;
  const s = study.data;
  const abilities = options.data?.abilities;
  return (
    <div className="space-y-5">
      {back}
      <PageHeader
        eyebrow={EYEBROW}
        title={s.title}
        status={
          <>
            <StatusBadge tone={s.status === "active" ? "info" : "neutral"}>{s.status === "active" ? "Active" : s.status === "complete" ? "Complete" : "Archived"}</StatusBadge>
            {s.imported && <StatusBadge tone="neutral">Imported</StatusBadge>}
          </>
        }
        actions={
          <>
            {abilities?.manageStudies && (
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil />
                Edit study
              </Button>
            )}
            {abilities?.editRecommendation && <NewRecommendationLink studyId={String(s.id)} />}
          </>
        }
      />
      <dl className="grid grid-cols-2 gap-4 rounded-lg border bg-card p-4 sm:grid-cols-4 xl:grid-cols-6">
        <Detail label="Study code">{s.studyCode}</Detail>
        <Detail label="Type">{s.studyType}</Detail>
        <Detail label="Year">{s.year}</Detail>
        <Detail label="Study date">{s.studyDate ? formatDate(s.studyDate) : null}</Detail>
        <Detail label="Areas">{s.areas.map((a) => a.name).join(", ")}</Detail>
        <Detail label="ID prefix">{s.recommendationPrefix}</Detail>
        <Detail label="Recommendations">{s.counts.recommendations}</Detail>
        <Detail label="Scenarios">{s.counts.scenarios}</Detail>
        <Detail label="Pending review">{s.counts.pending}</Detail>
        <Detail label="Open actions">{s.counts.openActions}</Detail>
        <Detail label="Closed">{s.counts.closed}</Detail>
        {s.sourceFileName && (
          <Detail label="Source">
            {s.sourceFileName}
            {s.sourceSheetName ? ` · sheet “${s.sourceSheetName}”` : ""}
          </Detail>
        )}
        {s.description && (
          <Detail label="Description" className="col-span-2 sm:col-span-4 xl:col-span-6">
            {s.description}
          </Detail>
        )}
      </dl>
      <RegisterPage title={s.title} initial={initial} study={s} />
      {editing && options.data && <StudyDialog options={options.data} study={s} onClose={() => setEditing(false)} />}
    </div>
  );
}
