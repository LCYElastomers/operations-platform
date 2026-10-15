"use client";

import { Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { DashboardToolbar } from "@/components/common/dashboard-toolbar";
import { FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { buttonVariants } from "@/components/ui/button";
import { TableSection, TD, TH } from "@/features/quality/cost/cost-shared";
import { formatDate } from "@/features/quality/cost/format";
import { useUrlState } from "@/lib/use-url-state";
import { cn } from "@/lib/utils";

import {
  ACTION_STATUS_LABELS,
  actionHref,
  actionsHref,
  registerHref,
  RISK_LABELS,
  RISKS,
  type Dashboard,
  type DashboardItem,
  type Risk,
} from "./api";
import { ActionStatusBadge, ContextPanel, EYEBROW, NoPsmData, PsmError, RiskBadge } from "./psm-shared";
import { usePsmDashboard, usePsmOptions } from "./use-psm";

/** What the user selected on the dashboard, and where its View button goes. */
export type Selection = {
  key: string;
  title: string;
  description?: string;
  details?: { label: string; value: React.ReactNode }[];
  href: string;
  viewLabel?: string;
};

type Scope = { studyId: string };

const readScope = (params: URLSearchParams): Scope => ({ studyId: params.get("studyId") ?? "" });
const writeScope = (params: URLSearchParams, value: Scope) => {
  if (value.studyId) params.set("studyId", value.studyId);
  else params.delete("studyId");
};

const STATUS_COLORS: Record<string, string> = {
  not_started: "#64748b",
  in_progress: "#2563eb",
  pending_verification: "#d97706",
  closed: "#059669",
};

function plural(count: number, one: string, many: string) {
  return `${count.toLocaleString("en-US")} ${count === 1 ? one : many}`;
}

/** A dashboard element that can be selected. Selecting shows its context; it never navigates. */
function Selectable({
  selection,
  selected,
  onSelect,
  className,
  children,
  label,
}: {
  selection: Selection;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
  className?: string;
  children: React.ReactNode;
  label?: string;
}) {
  const active = selected?.key === selection.key;
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={label}
      onClick={() => onSelect(selection)}
      className={cn(
        "rounded-lg text-left focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
        active && "ring-2 ring-primary",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function CommandCenter({ title, description, initialStudyId = "" }: { title: string; description?: string; initialStudyId?: string }) {
  const options = usePsmOptions();
  const [scope, setScope] = useUrlState<Scope>({ studyId: initialStudyId }, readScope, writeScope);
  const dashboard = usePsmDashboard(scope.studyId);
  const [selected, setSelected] = useState<Selection | null>(null);
  const data = dashboard.data;
  const study = scope.studyId;
  const studyName = options.data?.studies.find((s) => String(s.id) === study)?.name;
  const empty = data !== undefined && data.kpis.total === 0 && data.drafts === 0;

  const select = (next: Selection) => setSelected((current) => (current?.key === next.key ? null : next));

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={EYEBROW}
        title={title}
        description={description}
        actions={
          options.data?.abilities.importData ? (
            <Link href="/safety/psm/settings#import" className={buttonVariants({ variant: "outline", size: "sm" })}>
              <Upload />
              Import PHA workbook
            </Link>
          ) : undefined
        }
      />
      <DashboardToolbar
        actions={
          dashboard.isFetching &&
          !dashboard.isPending && (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          )
        }
      >
        <FilterSelect
          label="PHA study"
          placeholder="All studies"
          options={(options.data?.studies ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
          value={study}
          onChange={(event) => {
            setSelected(null);
            setScope({ studyId: event.target.value });
          }}
          className="pointer-coarse:h-11"
        />
      </DashboardToolbar>
      {dashboard.isError ? (
        <PsmError error={dashboard.error} onRetry={() => void dashboard.refetch()} />
      ) : empty ? (
        <NoPsmData filtered={Boolean(study)} />
      ) : (
        <>
          <KpiCards data={data} study={study} selected={selected} onSelect={select} />
          {data && (
            <>
              {data.drafts > 0 && (
                <p className="text-sm text-muted-foreground">
                  {plural(data.drafts, "draft recommendation is", "draft recommendations are")} not counted until finalized.
                </p>
              )}
              <Lifecycle data={data} study={study} selected={selected} onSelect={select} />
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <RiskPanel
                  title="Scenario risk"
                  description="Every hazard scenario by its own risk rating. A recommendation with several scenarios counts once per scenario."
                  counts={data.scenarioRisks}
                  noun={["scenario", "scenarios"]}
                  keyPrefix="scenario-risk"
                  href={(risk) => registerHref({ studyId: study, scenarioRisk: risk })}
                  viewLabel="View recommendations with these scenarios"
                  selected={selected}
                  onSelect={select}
                />
                <RiskPanel
                  title="Governing risk"
                  description="Each recommendation by the highest risk among its scenarios."
                  counts={data.governingRisks}
                  noun={["recommendation", "recommendations"]}
                  keyPrefix="governing-risk"
                  href={(risk) => registerHref({ studyId: study, governingRisk: risk })}
                  viewLabel="View recommendations"
                  selected={selected}
                  onSelect={select}
                />
              </div>
              <Matrix data={data} study={study} selected={selected} onSelect={select} />
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Departments data={data} study={study} selected={selected} onSelect={select} />
                <Aging data={data} study={study} selected={selected} onSelect={select} />
              </div>
              <Deadlines data={data} study={study} selected={selected} onSelect={select} />
              <Distribution data={data} study={study} selected={selected} onSelect={select} />
              <BarChart
                title="Actions by department and status"
                description={studyName ? `Study: ${studyName}.` : "All studies."}
                orientation="horizontal"
                height={Math.max(160, data.departments.length * 34 + 60)}
                categories={data.departments.map((d) => d.department)}
                series={["not_started", "in_progress", "pending_verification", "closed"].map((status) => ({
                  name: ACTION_STATUS_LABELS[status],
                  values: data.departments.map((d) => d.counts[status] ?? 0),
                  color: STATUS_COLORS[status],
                  stack: "status",
                }))}
                emptyState={<p className="px-4 py-6 text-sm text-muted-foreground">No actions yet.</p>}
              />
            </>
          )}
          {selected && (
            <ContextPanel
              title={selected.title}
              description={selected.description}
              details={selected.details}
              viewHref={selected.href}
              viewLabel={selected.viewLabel}
              onClear={() => setSelected(null)}
            />
          )}
        </>
      )}
    </div>
  );
}

type PanelProps = {
  data: Dashboard;
  study: string;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
};

function KpiCards({
  data,
  study,
  selected,
  onSelect,
}: Omit<PanelProps, "data"> & { data: Dashboard | undefined }) {
  const k = data?.kpis;
  const loading = data === undefined;
  const card = (
    key: string,
    label: string,
    value: number | null,
    caption: string,
    href: string,
    description: string,
    viewLabel: string,
  ) => (
    <Selectable
      key={key}
      selection={{ key: `kpi-${key}`, title: `${label}: ${value ?? "—"}`, description, href, viewLabel }}
      selected={selected}
      onSelect={onSelect}
      className="h-full"
    >
      <MetricCard label={label} value={value} caption={caption} loading={loading} className="h-full hover:bg-muted/40" />
    </Selectable>
  );
  const recommendations = registerHref({ studyId: study });
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {card("total", "Recommendations", k?.total ?? null, "Official recommendations in scope", recommendations, "Every official recommendation in scope.", "View recommendations")}
        {card("pending", "Pending review", k?.pending ?? null, "No disposition yet", registerHref({ studyId: study, disposition: "pending_review" }), "Recommendations waiting for a disposition decision.", "View recommendations")}
        {card("accepted", "Accepted", k?.accepted ?? null, "Each has one action", registerHref({ studyId: study, disposition: "accepted" }), "Accepted recommendations; each generated one action.", "View recommendations")}
        {card("rejected", "Rejected", k?.rejected ?? null, "With a documented justification", registerHref({ studyId: study, disposition: "rejected" }), "Rejected recommendations and their justifications.", "View recommendations")}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {card("not-started", "Not started", k?.notStarted ?? null, "Open actions", actionsHref({ studyId: study, tab: "not_started" }), "Actions not yet started.", "View actions")}
        {card("in-progress", "In progress", k?.inProgress ?? null, "Open actions", actionsHref({ studyId: study, tab: "in_progress" }), "Actions being worked on.", "View actions")}
        {card("verification", "Pending verification", k?.pendingVerification ?? null, "Closure requested", actionsHref({ studyId: study, tab: "pending_verification" }), "Actions waiting for closure verification.", "View actions")}
        {card(
          "closed",
          "Closed",
          k?.closed ?? null,
          k ? (k.closurePct === null ? "No actions yet" : `${k.closurePct}% of ${plural(k.actions, "action", "actions")}`) : "",
          actionsHref({ studyId: study, tab: "closed" }),
          "Actions closed after verification.",
          "View actions",
        )}
        {card("overdue", "Overdue", k?.overdue ?? null, "Open, due date passed", actionsHref({ studyId: study, tab: "overdue" }), "Open actions whose due date has passed. Closed actions and actions without a due date are not overdue.", "View actions")}
        {card("scheduling", "Needs scheduling", k?.needsScheduling ?? null, "Open, no due date", actionsHref({ studyId: study, dueState: "no_due_date" }), "Open actions without a due date. They are not counted as overdue.", "View actions")}
      </div>
    </div>
  );
}

function Lifecycle({ data, study, selected, onSelect }: PanelProps) {
  const stages = [...data.lifecycle, data.rejected];
  return (
    <TableSection
      id="psm-lifecycle"
      title="Recommendation lifecycle"
      description="A recommendation counts in every stage it has reached. Rejected recommendations leave the flow after review."
    >
      <ol className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-4 xl:grid-cols-8">
        {stages.map((stage) => (
          <li key={stage.code}>
            <Selectable
              selection={{
                key: `stage-${stage.code}`,
                title: `${stage.label}: ${stage.count}`,
                description: stage.definition,
                href: registerHref({ studyId: study, stage: stage.code }),
                viewLabel: "View recommendations",
              }}
              selected={selected}
              onSelect={onSelect}
              className={cn(
                "flex h-full w-full flex-col rounded-md border p-3 hover:bg-muted/40",
                stage.code === "rejected" && "border-dashed",
              )}
              label={`${stage.label}: ${stage.count}. ${stage.definition}`}
            >
              <span className="text-xs font-medium text-muted-foreground">{stage.label}</span>
              <span className="mt-1 text-2xl font-semibold tabular-nums">{stage.count}</span>
            </Selectable>
          </li>
        ))}
      </ol>
    </TableSection>
  );
}

function RiskPanel({
  title,
  description,
  counts,
  noun,
  keyPrefix,
  href,
  viewLabel,
  selected,
  onSelect,
}: {
  title: string;
  description: string;
  counts: Record<Risk, number>;
  noun: [string, string];
  keyPrefix: string;
  href: (risk: Risk) => string;
  viewLabel: string;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const total = RISKS.reduce((sum, risk) => sum + (counts[risk] ?? 0), 0);
  return (
    <TableSection id={`psm-${keyPrefix}`} title={title} description={description}>
      <ul className="space-y-2 p-3">
        {RISKS.map((risk) => {
          const count = counts[risk] ?? 0;
          const share = total > 0 ? (count / total) * 100 : 0;
          return (
            <li key={risk}>
              <Selectable
                selection={{
                  key: `${keyPrefix}-${risk}`,
                  title: `${title} ${RISK_LABELS[risk]}: ${plural(count, noun[0], noun[1])}`,
                  description,
                  href: href(risk),
                  viewLabel,
                }}
                selected={selected}
                onSelect={onSelect}
                className="flex w-full items-center gap-3 rounded-md p-2 hover:bg-muted/40"
                label={`${RISK_LABELS[risk]}: ${plural(count, noun[0], noun[1])}`}
              >
                <RiskBadge risk={risk} className="w-20 justify-center" />
                <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <span
                    className={cn(
                      "block h-full rounded-full",
                      risk === "high" ? "bg-destructive" : risk === "medium" ? "bg-warning" : "bg-success",
                    )}
                    style={{ width: `${share}%` }}
                  />
                </span>
                <span className="shrink-0 text-right text-sm whitespace-nowrap tabular-nums">{plural(count, noun[0], noun[1])}</span>
              </Selectable>
            </li>
          );
        })}
      </ul>
    </TableSection>
  );
}

function Matrix({ data, study, selected, onSelect }: PanelProps) {
  return (
    <TableSection
      id="psm-matrix"
      title="Governing risk × action status"
      description="Official recommendations that are not rejected, by governing risk and the status of their action. Select a cell to see what it holds."
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm tabular-nums">
          <caption className="sr-only">Governing risk by action status</caption>
          <thead className="border-b bg-muted/30">
            <tr>
              <th scope="col" className={TH}>
                Governing risk
              </th>
              {data.matrixColumns.map((column) => (
                <th key={column.code} scope="col" className={cn(TH, "text-center")}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {RISKS.map((risk) => (
              <tr key={risk} className="border-b border-border/60 last:border-b-0">
                <th scope="row" className={TD}>
                  <RiskBadge risk={risk} />
                </th>
                {data.matrixColumns.map((column) => {
                  const count = data.matrix[risk]?.[column.code] ?? 0;
                  return (
                    <td key={column.code} className="p-1 text-center">
                      <Selectable
                        selection={{
                          key: `matrix-${risk}-${column.code}`,
                          title: `${RISK_LABELS[risk]} risk · ${column.label}: ${plural(count, "recommendation", "recommendations")}`,
                          href: registerHref({ studyId: study, matrixRisk: risk, matrixColumn: column.code }),
                          viewLabel: "View recommendations",
                        }}
                        selected={selected}
                        onSelect={onSelect}
                        className={cn("w-full rounded-md px-3 py-2 text-center hover:bg-muted/60", count === 0 && "text-muted-foreground")}
                        label={`${RISK_LABELS[risk]} risk, ${column.label}: ${count}`}
                      >
                        {count}
                      </Selectable>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </TableSection>
  );
}

function Departments({ data, study, selected, onSelect }: PanelProps) {
  return (
    <TableSection id="psm-departments" title="Actions by department" description="Every active action, by the department responsible.">
      {data.departments.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No actions yet.</p>
      ) : (
        <ul className="divide-y">
          {data.departments.map((d) => {
            const open = (d.counts.not_started ?? 0) + (d.counts.in_progress ?? 0) + (d.counts.pending_verification ?? 0);
            const code = d.departmentId === null ? "unassigned" : String(d.departmentId);
            return (
              <li key={code}>
                <Selectable
                  selection={{
                    key: `department-${code}`,
                    title: d.department,
                    details: [
                      { label: "Not started", value: d.counts.not_started ?? 0 },
                      { label: "In progress", value: d.counts.in_progress ?? 0 },
                      { label: "Pending verification", value: d.counts.pending_verification ?? 0 },
                      { label: "Closed", value: d.counts.closed ?? 0 },
                    ],
                    href: actionsHref({ studyId: study, department: code }),
                    viewLabel: "View actions",
                  }}
                  selected={selected}
                  onSelect={onSelect}
                  className="flex w-full items-center justify-between gap-3 rounded-none px-4 py-2 text-sm hover:bg-muted/40"
                >
                  <span className="font-medium">{d.department}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {open} open · {d.counts.closed ?? 0} closed
                  </span>
                </Selectable>
              </li>
            );
          })}
        </ul>
      )}
    </TableSection>
  );
}

function Aging({ data, study, selected, onSelect }: PanelProps) {
  return (
    <TableSection id="psm-aging" title="Aging of open actions" description="Days since the action was generated.">
      <ul className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-4">
        {data.aging.map((bucket) => (
          <li key={bucket.code}>
            <Selectable
              selection={{
                key: `aging-${bucket.code}`,
                title: `Open actions ${bucket.label}: ${bucket.count}`,
                href: actionsHref({ studyId: study, aging: bucket.code, sort: "age", desc: true }),
                viewLabel: "View actions",
              }}
              selected={selected}
              onSelect={onSelect}
              className="flex w-full flex-col rounded-md border p-3 hover:bg-muted/40"
            >
              <span className="text-xs font-medium text-muted-foreground">{bucket.label}</span>
              <span className="mt-1 text-2xl font-semibold tabular-nums">{bucket.count}</span>
            </Selectable>
          </li>
        ))}
      </ul>
    </TableSection>
  );
}

function DeadlineList({
  title,
  items,
  empty,
  allHref,
  selected,
  onSelect,
}: {
  title: string;
  items: DashboardItem[];
  empty: string;
  allHref: string;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  return (
    <section aria-label={title} className="min-w-0">
      <header className="flex items-center justify-between gap-2 px-4 pt-3">
        <h3 className="text-sm font-semibold">
          {title} <span className="font-normal text-muted-foreground tabular-nums">({items.length})</span>
        </h3>
        <Link href={allHref} className="text-xs font-medium text-primary hover:underline">
          Open list
        </Link>
      </header>
      {items.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="divide-y">
          {items.slice(0, 8).map((item) => (
            <li key={item.actionId}>
              <Selectable
                selection={{
                  key: `deadline-${item.actionId}`,
                  title: `${item.actionNumber} · ${item.displayId}`,
                  description: item.title,
                  details: [
                    { label: "Owner", value: item.owner },
                    { label: "Department", value: item.department },
                    { label: "Due", value: item.dueDate ? formatDate(item.dueDate) : null },
                    { label: "Status", value: <ActionStatusBadge status={item.status} /> },
                  ],
                  href: actionHref(item.actionId),
                  viewLabel: "View action",
                }}
                selected={selected}
                onSelect={onSelect}
                className="flex w-full flex-col gap-0.5 rounded-none px-4 py-2 text-sm hover:bg-muted/40"
              >
                <span className="flex items-center gap-2">
                  <span className="font-medium">{item.actionNumber}</span>
                  <RiskBadge risk={item.governingRisk} />
                </span>
                <span className="truncate text-muted-foreground">
                  {item.owner ?? "No owner"} · due {formatDate(item.dueDate)}
                </span>
              </Selectable>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Deadlines({ data, study, selected, onSelect }: PanelProps) {
  return (
    <TableSection
      id="psm-deadlines"
      title="Deadlines"
      description={`Open actions by due date. ${plural(data.needsScheduling, "open action has no due date and needs scheduling; it is", "open actions have no due date and need scheduling; they are")} not overdue.`}
      actions={
        data.needsScheduling > 0 ? (
          <Link href={actionsHref({ studyId: study, dueState: "no_due_date" })} className="text-sm font-medium text-primary hover:underline">
            Needs scheduling ({data.needsScheduling})
          </Link>
        ) : undefined
      }
    >
      <div className="grid grid-cols-1 divide-y lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        <DeadlineList
          title="Overdue"
          items={data.overdue}
          empty="No open action is overdue."
          allHref={actionsHref({ studyId: study, tab: "overdue" })}
          selected={selected}
          onSelect={onSelect}
        />
        <DeadlineList
          title="Due in 7 days"
          items={data.due7}
          empty="Nothing due in the next 7 days."
          allHref={actionsHref({ studyId: study, dueState: "due_7" })}
          selected={selected}
          onSelect={onSelect}
        />
        <DeadlineList
          title="Due in 8–30 days"
          items={data.due30}
          empty="Nothing due in the next 30 days."
          allHref={actionsHref({ studyId: study, dueState: "due_30" })}
          selected={selected}
          onSelect={onSelect}
        />
      </div>
    </TableSection>
  );
}

function Distribution({ data, study, selected, onSelect }: PanelProps) {
  return (
    <TableSection
      id="psm-distribution"
      title="Action distribution by owner"
      description="Open actions held by each owner, by status. Select an owner to see their actions."
    >
      {data.distribution.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No open actions.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm tabular-nums">
            <caption className="sr-only">Action distribution by owner</caption>
            <thead className="border-b bg-muted/30">
              <tr>
                {["Owner", "Not started", "In progress", "Pending verification", "Overdue", "Total active"].map((h, i) => (
                  <th key={h} scope="col" className={cn(TH, i > 0 && "text-right")}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.distribution.map((load) => {
                const key = load.ownerKey ?? "unassigned";
                const selection: Selection = {
                  key: `owner-${key}`,
                  title: load.owner,
                  details: [
                    { label: "Not started", value: load.notStarted },
                    { label: "In progress", value: load.inProgress },
                    { label: "Pending verification", value: load.pendingVerification },
                    { label: "Overdue", value: load.overdue },
                  ],
                  href: actionsHref({ studyId: study, owner: key }),
                  viewLabel: "View actions",
                };
                const active = selected?.key === selection.key;
                return (
                  <tr
                    key={key}
                    aria-selected={active}
                    onClick={() => onSelect(selection)}
                    className="cursor-pointer border-b border-border/60 last:border-b-0 hover:bg-muted/40 aria-selected:bg-primary/10"
                  >
                    <th scope="row" className={cn(TD, "font-medium")}>
                      <button
                        type="button"
                        aria-pressed={active}
                        onClick={(event) => {
                          event.stopPropagation();
                          onSelect(selection);
                        }}
                        className="rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                      >
                        {load.owner}
                      </button>
                    </th>
                    <td className={cn(TD, "text-right")}>{load.notStarted}</td>
                    <td className={cn(TD, "text-right")}>{load.inProgress}</td>
                    <td className={cn(TD, "text-right")}>{load.pendingVerification}</td>
                    <td className={cn(TD, "text-right")}>{load.overdue}</td>
                    <td className={cn(TD, "text-right font-medium")}>{load.totalActive}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </TableSection>
  );
}
