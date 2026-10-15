"use client";

import { useDeferredValue, useState } from "react";

import { ActiveFilters, type FilterChip } from "@/components/common/active-filters";
import { DashboardToolbar } from "@/components/common/dashboard-toolbar";
import { ExportMenu } from "@/components/common/export-menu";
import { FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { NotEntered, TableSection, TD, TH } from "@/features/quality/cost/cost-shared";
import { formatDate } from "@/features/quality/cost/format";
import { useUrlState } from "@/lib/use-url-state";
import { cn } from "@/lib/utils";

import {
  actionExportFilters,
  actionHref,
  actionParams,
  actionsFromParams,
  DUE_STATE_LABELS,
  EMPTY_ACTION_QUERY,
  RISK_LABELS,
  RISKS,
  type Action,
  type ActionQuery,
  type PsmOptions,
} from "./api";
import {
  ActionStatusBadge,
  AttentionBadges,
  ContextPanel,
  DueStateBadge,
  EYEBROW,
  Pagination,
  PsmError,
  RiskBadge,
  SELECT_ROW,
  SortHeader,
} from "./psm-shared";
import { useActions, usePsmOptions } from "./use-psm";

const TABS = [
  ["all", "All"],
  ["attention", "Needs attention"],
  ["not_started", "Not Started"],
  ["in_progress", "In Progress"],
  ["pending_verification", "Pending Verification"],
  ["overdue", "Overdue"],
  ["closed", "Closed"],
] as const;

const AGING_LABELS: Record<string, string> = { "0_30": "0–30 days", "31_60": "31–60 days", "61_90": "61–90 days", "90_plus": "90+ days" };

const SORTABLE: [string, string][] = [
  ["Action", "action"],
  ["Recommendation", "recommendation"],
  ["Area / Equipment", "equipment"],
  ["Governing risk", "risk"],
  ["Department", "department"],
  ["Owner", "owner"],
  ["Due date", "dueDate"],
  ["Status", "status"],
  ["Age (days)", "age"],
];

const writeQuery = (params: URLSearchParams, value: ActionQuery) => {
  for (const key of [...params.keys()]) params.delete(key);
  actionParams(value).forEach((v, k) => params.set(k, v));
};
const readQuery = (params: URLSearchParams) => actionsFromParams(Object.fromEntries(params));

function criteria(query: ActionQuery) {
  return JSON.stringify({ ...query, tab: undefined, sort: undefined, desc: undefined, page: undefined });
}

/**
 * Action Items: every action generated from an accepted recommendation, by
 * workflow tab. Filters, tab, sort and page live in the URL.
 */
export function ActionsPage({ title, description, initial }: { title: string; description?: string; initial: ActionQuery }) {
  const options = usePsmOptions();
  const [filters, setQuery] = useUrlState<ActionQuery>(initial, readQuery, writeQuery);
  const query = { ...filters, q: useDeferredValue(filters.q) };
  const actions = useActions(query);
  const [selected, setSelected] = useState<Action | null>(null);
  const data = actions.data;
  const filtered = criteria(filters) !== criteria(EMPTY_ACTION_QUERY);

  const setFilters = (next: ActionQuery, replace = false) => {
    setSelected(null);
    setQuery({ ...next, page: 1 }, { replace });
  };
  const clear = () => setFilters({ ...EMPTY_ACTION_QUERY, tab: filters.tab, sort: filters.sort, desc: filters.desc });
  const chips = filterChips(filters, options.data, (patch) => setFilters({ ...filters, ...patch }));
  const counts = data?.tabCounts;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow={EYEBROW} title={title} description={description} />
      <DashboardToolbar
        actions={
          actions.isFetching &&
          !actions.isPending && (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          )
        }
        exportMenu={
          <ExportMenu
            reportKey="psm-actions"
            title="PSM action items"
            formats={["xlsx"]}
            requires={["psm.view", "psm.export"]}
            disabled={!data}
            context={() => ({ period: { mode: "all" }, filters: actionExportFilters(filters) })}
          />
        }
      >
        <FilterInput
          label="Search"
          type="search"
          placeholder="Action, recommendation, equipment, owner…"
          value={filters.q}
          onChange={(event) => setFilters({ ...filters, q: event.target.value }, true)}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Study"
          options={(options.data?.studies ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
          value={filters.studyId}
          onChange={(event) => setFilters({ ...filters, studyId: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Department"
          options={[
            ...(options.data?.departments ?? []).map((d) => ({ value: String(d.id), label: d.name })),
            { value: "unassigned", label: "Unassigned" },
          ]}
          value={filters.department}
          onChange={(event) => setFilters({ ...filters, department: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Owner"
          options={[
            ...(options.data?.owners ?? []).map((o) => ({ value: o.code, label: o.label })),
            { value: "unassigned", label: "Unassigned" },
          ]}
          value={filters.owner}
          onChange={(event) => setFilters({ ...filters, owner: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Governing risk"
          options={RISKS.map((risk) => ({ value: risk, label: RISK_LABELS[risk] }))}
          value={filters.risk}
          onChange={(event) => setFilters({ ...filters, risk: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Due"
          options={Object.entries(DUE_STATE_LABELS).map(([value, label]) => ({ value, label }))}
          value={filters.dueState}
          onChange={(event) => setFilters({ ...filters, dueState: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Age (open)"
          options={Object.entries(AGING_LABELS).map(([value, label]) => ({ value, label }))}
          value={filters.aging}
          onChange={(event) => setFilters({ ...filters, aging: event.target.value })}
          className="pointer-coarse:h-11"
        />
      </DashboardToolbar>
      <ActiveFilters chips={chips} onClearAll={clear} />
      <Tabs
        label="Action workflow"
        items={TABS.map(([value, label]) => ({ value, label: counts ? `${label} (${counts[value] ?? 0})` : label }))}
        value={filters.tab}
        onValueChange={(tab) => setFilters({ ...filters, tab })}
      >
        <div className="space-y-4">
          {actions.isError ? (
            <PsmError error={actions.error} onRetry={() => void actions.refetch()} />
          ) : actions.isPending ? (
            <p className="py-6 text-sm text-muted-foreground">Loading actions…</p>
          ) : data && data.rows.length === 0 ? (
            <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
              {filtered || filters.tab !== "all" ? (
                <>
                  <p>No actions match.</p>
                  {filtered && (
                    <Button variant="outline" size="sm" className="mt-3" onClick={clear}>
                      Clear filters
                    </Button>
                  )}
                </>
              ) : (
                <p>No actions yet. An action is generated when a PHA recommendation is accepted.</p>
              )}
            </div>
          ) : (
            data && (
              <TableSection
                id="psm-actions"
                title="Action items"
                description={`${data.total.toLocaleString("en-US")} ${data.total === 1 ? "action" : "actions"}. Select a row to see it, then View to open it.`}
              >
                <ActionTable
                  rows={data.rows}
                  query={filters}
                  selectedId={selected?.id ?? null}
                  onSelect={(row) => setSelected((current) => (current?.id === row.id ? null : row))}
                  onSort={(sort, desc) => setQuery({ ...filters, sort, desc, page: 1 })}
                />
                <Pagination
                  page={filters.page}
                  total={data.total}
                  shown={data.rows.length}
                  noun={["action", "actions"]}
                  onPage={(page) => setQuery({ ...filters, page })}
                />
              </TableSection>
            )
          )}
          {selected && (
            <ContextPanel
              title={`${selected.actionNumber} · ${selected.recommendationDisplayId}`}
              description={<span className="line-clamp-3">{selected.title}</span>}
              details={[
                { label: "Status", value: <ActionStatusBadge status={selected.status} /> },
                { label: "Owner", value: selected.ownerName },
                { label: "Due date", value: selected.dueDate ? formatDate(selected.dueDate) : null },
                { label: "Governing risk", value: <RiskBadge risk={selected.governingRisk} /> },
              ]}
              viewHref={actionHref(selected.id)}
              viewLabel="View action"
              onClear={() => setSelected(null)}
            />
          )}
        </div>
      </Tabs>
    </div>
  );
}

function filterChips(filters: ActionQuery, options: PsmOptions | undefined, set: (patch: Partial<ActionQuery>) => void): FilterChip[] {
  const chips: FilterChip[] = [];
  const add = (key: string, label: string, reset: Partial<ActionQuery>) => chips.push({ key, label, onRemove: () => set(reset) });
  const name = (list: { id: number; name: string }[] | undefined, id: string) => list?.find((item) => String(item.id) === id)?.name ?? id;
  if (filters.studyId) add("study", `Study: ${name(options?.studies, filters.studyId)}`, { studyId: "" });
  if (filters.q.trim()) add("q", `Search: “${filters.q.trim()}”`, { q: "" });
  if (filters.department)
    add("department", `Department: ${filters.department === "unassigned" ? "Unassigned" : name(options?.departments, filters.department)}`, { department: "" });
  if (filters.owner)
    add("owner", `Owner: ${filters.owner === "unassigned" ? "Unassigned" : (options?.owners.find((o) => o.code === filters.owner)?.label ?? filters.owner)}`, { owner: "" });
  if (filters.risk) add("risk", `Governing risk: ${RISK_LABELS[filters.risk] ?? filters.risk}`, { risk: "" });
  if (filters.dueState) add("dueState", `Due: ${DUE_STATE_LABELS[filters.dueState] ?? filters.dueState}`, { dueState: "" });
  if (filters.aging) add("aging", `Open for ${AGING_LABELS[filters.aging] ?? filters.aging}`, { aging: "" });
  return chips;
}

function ActionTable({
  rows,
  query,
  selectedId,
  onSelect,
  onSort,
}: {
  rows: Action[];
  query: Pick<ActionQuery, "sort" | "desc">;
  selectedId: number | null;
  onSelect: (row: Action) => void;
  onSort: (sort: string, desc: boolean) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1300px] text-left text-sm">
        <caption className="sr-only">PSM action items</caption>
        <thead className="border-b bg-muted/30">
          <tr>
            {SORTABLE.map(([label, column]) => (
              <SortHeader key={column} label={label} column={column} sort={query.sort} desc={query.desc} onSort={onSort} className={TH} />
            ))}
            <th scope="col" className={TH}>
              Needs attention
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const active = row.id === selectedId;
            return (
              <tr key={row.id} aria-selected={active} onClick={() => onSelect(row)} className={SELECT_ROW}>
                <th scope="row" className={cn(TD, "whitespace-nowrap")}>
                  <button
                    type="button"
                    aria-pressed={active}
                    aria-label={`Select ${row.actionNumber}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(row);
                    }}
                    className="font-medium rounded-sm focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                  >
                    {row.actionNumber}
                  </button>
                </th>
                <td className={cn(TD, "max-w-80 min-w-64")}>
                  <span className="font-medium">{row.recommendationDisplayId}</span>
                  <span className="line-clamp-2 text-muted-foreground" title={row.title}>
                    {row.title}
                  </span>
                </td>
                <td className={cn(TD, "max-w-48")}>
                  <span className="line-clamp-2">{row.areaEquipment}</span>
                </td>
                <td className={TD}>
                  <RiskBadge risk={row.governingRisk} />
                </td>
                <td className={TD}>{row.department ?? <NotEntered label="—" />}</td>
                <td className={cn(TD, "whitespace-nowrap")}>{row.ownerName ?? <NotEntered label="—" />}</td>
                <td className={cn(TD, "whitespace-nowrap")}>
                  {row.dueDate ? formatDate(row.dueDate) : <NotEntered label="—" />}
                  <span className="mt-0.5 block">
                    <DueStateBadge state={row.dueState} />
                  </span>
                </td>
                <td className={TD}>
                  <ActionStatusBadge status={row.status} />
                </td>
                <td className={cn(TD, "tabular-nums")}>{row.ageDays}</td>
                <td className={TD}>
                  <AttentionBadges reasons={row.attention} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
