"use client";

import { AlertTriangle, ChartColumn, ClipboardList, Eye } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { defaultReportingYear } from "../incidents/grid";
import { ReportingYearSelect } from "../incidents/reporting-year-select";
import { describeObservationError, type Observation } from "./api";
import { MonthSummary } from "./month-summary";
import { ObservationCard } from "./observation-card";
import {
  draftFromObservation,
  emptyDraft,
  localIsoDate,
  monthName,
  nextDraft,
  toInput,
  validateDraft,
  type ObservationDraft,
} from "./observation-data";
import { ObservationForm } from "./observation-form";
import {
  useCreateObservation,
  useDeleteObservation,
  useObservationCategories,
  useObservations,
  useObservationSummary,
  useUpdateObservation,
} from "./use-observations";

const PAGE_SIZE = 50;

type Period = { year: number; month: number };

function isAccessDenied(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

function periodOf(isoDate: string): Period {
  const [year, month] = isoDate.split("-").map(Number);
  return { year, month };
}

type ObservationsPageProps = { title: string; description?: string };

export function ObservationsPage({ title, description }: ObservationsPageProps) {
  const [today, setToday] = useState(() => localIsoDate(new Date()));
  const current = periodOf(today);
  const [period, setPeriod] = useState<Period>(() => ({
    year: defaultReportingYear(current.year),
    month: current.month,
  }));
  const [limit, setLimit] = useState(PAGE_SIZE);

  // A tablet left open overnight should not keep offering yesterday as "today".
  useEffect(() => {
    const timer = window.setInterval(() => setToday(localIsoDate(new Date())), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const categories = useObservationCategories();
  const list = useObservations({ year: period.year, month: period.month, limit });
  const summary = useObservationSummary(period.year, period.month);
  const create = useCreateObservation();
  const update = useUpdateObservation();
  const remove = useDeleteObservation();

  const [draft, setDraft] = useState<ObservationDraft>(() => emptyDraft(today));
  const [attempted, setAttempted] = useState(false);
  const [lastAddedId, setLastAddedId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [editing, setEditing] = useState<{ observation: Observation; draft: ObservationDraft } | null>(null);
  const [editAttempted, setEditAttempted] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const canEdit = categories.data?.canEdit ?? list.data?.canEdit ?? false;
  const errors = useMemo(() => validateDraft(draft, today), [draft, today]);
  const editErrors = useMemo(
    () => (editing ? validateDraft(editing.draft, today) : {}),
    [editing, today],
  );

  const periodLabel = `${monthName(period.month)} ${period.year}`;
  const startedMonths =
    period.year < current.year ? 12 : period.year === current.year ? current.month : 0;
  const monthOptions = Array.from({ length: Math.max(startedMonths, period.month) }, (_, index) => ({
    value: String(index + 1),
    label: monthName(index + 1),
  }));

  const choosePeriod = (next: Period) => {
    setPeriod(next);
    setLimit(PAGE_SIZE);
    setEditing(null);
    setConfirmDeleteId(null);
  };

  const submitNew = () => {
    setAttempted(true);
    setNotice(null);
    if (Object.keys(errors).length > 0) return;
    create.mutate(toInput(draft), {
      onSuccess: (saved) => {
        setLastAddedId(saved.id);
        setNotice(`Observation added: ${saved.categoryName}, ${saved.observedOn}.`);
        setDraft(nextDraft(draft));
        setAttempted(false);
        const savedPeriod = periodOf(saved.observedOn);
        if (savedPeriod.year !== period.year || savedPeriod.month !== period.month) {
          choosePeriod(savedPeriod);
        }
      },
    });
  };

  const submitEdit = () => {
    if (!editing) return;
    setEditAttempted(true);
    if (Object.keys(editErrors).length > 0) return;
    update.mutate(
      {
        id: editing.observation.id,
        input: toInput(editing.draft),
        expectedUpdatedAt: editing.observation.updatedAt,
      },
      {
        onSuccess: (saved) => {
          setEditing(null);
          setNotice(`Observation updated: ${saved.categoryName}, ${saved.observedOn}.`);
        },
        onError: (error) => {
          if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
            setEditing(null);
            setNotice(describeObservationError(error));
          }
        },
      },
    );
  };

  const confirmDelete = (id: number) => {
    remove.mutate(id, {
      onSuccess: () => {
        setConfirmDeleteId(null);
        setNotice("Observation deleted.");
        if (lastAddedId === id) setLastAddedId(null);
      },
      onError: (error) => {
        setConfirmDeleteId(null);
        setNotice(describeObservationError(error));
      },
    });
  };

  const loadError = categories.error ?? list.error;
  const denied = isAccessDenied(loadError);
  const observations = list.data?.observations ?? [];
  const totalMatching = list.data?.totalMatching ?? 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Safety Observations"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/observations/dashboard"
            className={buttonVariants({ variant: "outline", className: "pointer-coarse:h-11" })}
          >
            <ChartColumn />
            Open dashboard
          </Link>
        }
      />

      {denied ? (
        <EmptyState
          icon={AlertTriangle}
          title="Safety Observations are not available to you"
          description={describeObservationError(loadError)}
        />
      ) : (
        <div className="grid grid-cols-1 items-start gap-5 min-[1400px]:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
          {canEdit ? (
            <section
              aria-labelledby="new-observation-heading"
              className="rounded-lg border bg-card p-4 sm:p-5"
            >
              <h2 id="new-observation-heading" className="mb-4 text-base font-semibold">
                New Observation
              </h2>
              {categories.isPending ? (
                <div className="h-96 animate-pulse rounded-md bg-muted/70" aria-busy>
                  <span className="sr-only">Loading categories</span>
                </div>
              ) : categories.isError ? (
                <EmptyState
                  variant="plain"
                  icon={AlertTriangle}
                  title="Could not load categories"
                  description={describeObservationError(categories.error)}
                  action={
                    <Button variant="outline" onClick={() => void categories.refetch()}>
                      Retry
                    </Button>
                  }
                />
              ) : (
                <ObservationForm
                  draft={draft}
                  onChange={(next) => {
                    setDraft(next);
                    if (create.isError) create.reset();
                  }}
                  onSubmit={submitNew}
                  categories={categories.data.categories}
                  errors={errors}
                  showErrors={attempted}
                  today={today}
                  submitLabel="Add Observation"
                  pending={create.isPending}
                  saveError={create.isError ? describeObservationError(create.error) : null}
                />
              )}
            </section>
          ) : (
            categories.isSuccess && (
              <p className="flex items-center gap-2 rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground">
                <Eye aria-hidden className="size-4 shrink-0" />
                You have view-only access. Observations cannot be added or changed with your permissions.
              </p>
            )
          )}

          <div className="min-w-0 space-y-4">
            <FilterBar
              actions={
                list.isFetching && !list.isPending ? (
                  <StatusBadge tone="pending" pulse>
                    Updating
                  </StatusBadge>
                ) : undefined
              }
            >
              <ReportingYearSelect
                year={period.year}
                onChange={(year) =>
                  choosePeriod({
                    year,
                    month: year === current.year ? Math.min(period.month, current.month) : period.month,
                  })
                }
              />
              <FilterSelect
                label="Month"
                placeholder={false}
                options={monthOptions}
                value={String(period.month)}
                onChange={(event) => choosePeriod({ ...period, month: Number(event.target.value) })}
                className="pointer-coarse:h-11"
              />
            </FilterBar>

            <MonthSummary
              period={periodLabel}
              counts={summary.data?.counts}
              categories={summary.data?.categories ?? []}
              loading={summary.isPending}
            />

            <p role="status" aria-live="polite" className="min-h-5 text-sm font-medium text-primary">
              {notice}
            </p>

            <section aria-labelledby="recent-observations-heading" className="space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <h2
                  id="recent-observations-heading"
                  className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
                >
                  Recent Observations · {periodLabel}
                </h2>
                {list.isSuccess && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {observations.length < totalMatching
                      ? `${observations.length} of ${totalMatching}`
                      : `${totalMatching} ${totalMatching === 1 ? "observation" : "observations"}`}
                  </span>
                )}
              </div>

              {list.isPending ? (
                <div className="space-y-3" aria-busy>
                  {[0, 1, 2].map((key) => (
                    <div key={key} className="h-24 animate-pulse rounded-lg border bg-muted/50" />
                  ))}
                </div>
              ) : list.isError ? (
                <EmptyState
                  icon={AlertTriangle}
                  title="Could not load observations"
                  description={describeObservationError(list.error)}
                  action={
                    <Button variant="outline" onClick={() => void list.refetch()}>
                      Retry
                    </Button>
                  }
                />
              ) : observations.length === 0 ? (
                <EmptyState
                  icon={ClipboardList}
                  title={`No observations for ${periodLabel}`}
                  description={canEdit ? "Observations you add for this month will appear here." : undefined}
                />
              ) : (
                <ul className="space-y-3">
                  {observations.map((observation) => (
                    <li key={observation.id}>
                      {editing?.observation.id === observation.id && categories.isSuccess ? (
                        <section
                          aria-label="Edit observation"
                          className="rounded-lg border border-primary/50 bg-card p-4 ring-2 ring-primary/20"
                        >
                          <h3 className="mb-4 text-sm font-semibold">Edit observation</h3>
                          <ObservationForm
                            draft={editing.draft}
                            onChange={(next) => {
                              setEditing({ ...editing, draft: next });
                              if (update.isError) update.reset();
                            }}
                            onSubmit={submitEdit}
                            onCancel={() => setEditing(null)}
                            categories={withCurrentCategory(categories.data.categories, observation)}
                            errors={editErrors}
                            showErrors={editAttempted}
                            today={today}
                            submitLabel="Save Changes"
                            pending={update.isPending}
                            saveError={update.isError ? describeObservationError(update.error) : null}
                          />
                        </section>
                      ) : (
                        <ObservationCard
                          observation={observation}
                          canEdit={canEdit}
                          highlighted={observation.id === lastAddedId}
                          confirmingDelete={confirmDeleteId === observation.id}
                          deleting={remove.isPending && remove.variables === observation.id}
                          onEdit={() => {
                            update.reset();
                            setEditAttempted(false);
                            setConfirmDeleteId(null);
                            setEditing({ observation, draft: draftFromObservation(observation) });
                          }}
                          onRequestDelete={() => {
                            setEditing(null);
                            setConfirmDeleteId(observation.id);
                          }}
                          onCancelDelete={() => setConfirmDeleteId(null)}
                          onConfirmDelete={() => confirmDelete(observation.id)}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              )}

              {list.isSuccess && observations.length < totalMatching && (
                <Button
                  variant="outline"
                  className="h-12 w-full"
                  onClick={() => setLimit((value) => value + PAGE_SIZE)}
                  disabled={list.isFetching}
                >
                  Show more observations
                </Button>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

/** A retired category stays selectable for the observation that already uses it. */
function withCurrentCategory(
  categories: { id: number; code: string; name: string }[],
  observation: Observation,
) {
  if (categories.some((category) => category.id === observation.categoryId)) return categories;
  return [
    ...categories,
    { id: observation.categoryId, code: observation.categoryCode, name: observation.categoryName },
  ];
}
