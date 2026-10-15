"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { ActiveFilters, type FilterChip } from "@/components/common/active-filters";
import { DashboardToolbar } from "@/components/common/dashboard-toolbar";
import { ExportMenu } from "@/components/common/export-menu";
import { FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { NotEntered, TableSection, TD, TH } from "@/features/quality/cost/cost-shared";
import { formatDate } from "@/features/quality/cost/format";
import { useUrlState } from "@/lib/use-url-state";
import { cn } from "@/lib/utils";

import {
  ACTION_STATUS_LABELS,
  DISPOSITION_LABELS,
  DUE_STATE_LABELS,
  EMPTY_REGISTER_QUERY,
  recommendationHref,
  registerExportFilters,
  registerFromParams,
  registerParams,
  RISK_LABELS,
  RISKS,
  studyHref,
  type PsmOptions,
  type RecommendationRow,
  type RegisterQuery,
  type Study,
} from "./api";
import {
  ActionStatusBadge,
  ContextPanel,
  DispositionBadge,
  DueStateBadge,
  EYEBROW,
  NoPsmData,
  Pagination,
  PsmError,
  RiskBadge,
  SELECT_ROW,
  SortHeader,
} from "./psm-shared";
import { StudyDialog } from "./study-dialog";
import { usePsmOptions, useRegister, useStudies } from "./use-psm";

const STAGE_LABELS: Record<string, string> = {
  identified: "Identified",
  reviewed: "Reviewed",
  accepted: "Accepted",
  assigned: "Assigned",
  in_progress: "In Progress",
  verification: "Verification",
  closed: "Closed",
  rejected: "Rejected",
};
const MATRIX_LABELS: Record<string, string> = { no_action: "No Action / Pending Disposition", ...ACTION_STATUS_LABELS };

const writeQuery = (params: URLSearchParams, value: RegisterQuery) => {
  for (const key of [...params.keys()]) params.delete(key);
  registerParams(value).forEach((v, k) => params.set(k, v));
};
const readQuery = (params: URLSearchParams) => registerFromParams(Object.fromEntries(params));

function criteria(query: RegisterQuery) {
  return JSON.stringify({ ...query, sort: undefined, desc: undefined, page: undefined });
}

export function NewRecommendationLink({ studyId }: { studyId?: string }) {
  return (
    <Link
      href={`/safety/psm/pha/recommendations/new${studyId ? `?studyId=${encodeURIComponent(studyId)}` : ""}`}
      className={buttonVariants({ className: "pointer-coarse:h-11" })}
    >
      <Plus />
      New recommendation
    </Link>
  );
}

/**
 * PHA Management: the studies and every recommendation with its scenarios,
 * disposition and action. Filters, sort and page live in the URL, so a
 * Command Center figure opens exactly its recommendations.
 */
export function RegisterPage({
  title,
  description,
  initial,
  study,
}: {
  title: string;
  description?: string;
  initial: RegisterQuery;
  /** Set on a study's page: the register is limited to it. */
  study?: Study;
}) {
  const options = usePsmOptions();
  const fixed = study ? String(study.id) : "";
  const [stored, setQuery] = useUrlState<RegisterQuery>(initial, readQuery, writeQuery);
  const filters = fixed ? { ...stored, studyId: fixed } : stored;
  const query = { ...filters, q: useDeferredValue(filters.q) };
  const register = useRegister(query);
  const [selected, setSelected] = useState<RecommendationRow | null>(null);
  const data = register.data;
  const empty = { ...EMPTY_REGISTER_QUERY, studyId: fixed };
  const filtered = criteria(filters) !== criteria(empty);
  const abilities = options.data?.abilities;

  const setFilters = (next: RegisterQuery, replace = false) => {
    setSelected(null);
    setQuery({ ...next, page: 1 }, { replace });
  };
  const clear = () => setFilters({ ...empty, sort: filters.sort, desc: filters.desc });

  const chips = filterChips(filters, options.data, fixed, (patch) => setFilters({ ...filters, ...patch }));

  return (
    <div className="space-y-5">
      {!study && (
        <PageHeader
          eyebrow={EYEBROW}
          title={title}
          description={description}
          actions={abilities?.editRecommendation ? <NewRecommendationLink studyId={filters.studyId} /> : undefined}
        />
      )}
      {!study && <Studies abilities={abilities} options={options.data} />}
      <DashboardToolbar
        actions={
          register.isFetching &&
          !register.isPending && (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          )
        }
        exportMenu={
          <ExportMenu
            reportKey="psm-recommendations"
            title="PHA recommendations"
            formats={["xlsx"]}
            requires={["psm.view", "psm.export"]}
            disabled={!data}
            context={() => ({ period: { mode: "all" }, filters: registerExportFilters(filters) })}
          />
        }
      >
        <FilterInput
          label="Search"
          type="search"
          placeholder="ID, equipment, text, scenario…"
          value={filters.q}
          onChange={(event) => setFilters({ ...filters, q: event.target.value }, true)}
          className="pointer-coarse:h-11"
        />
        {!fixed && (
          <FilterSelect
            label="Study"
            options={(options.data?.studies ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
            value={filters.studyId}
            onChange={(event) => setFilters({ ...filters, studyId: event.target.value })}
            className="pointer-coarse:h-11"
          />
        )}
        <FilterSelect
          label="Disposition"
          options={Object.entries(DISPOSITION_LABELS).map(([value, label]) => ({ value, label }))}
          value={filters.disposition}
          onChange={(event) => setFilters({ ...filters, disposition: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Action status"
          options={[
            { value: "none", label: "No action" },
            ...Object.entries(ACTION_STATUS_LABELS).map(([value, label]) => ({ value, label })),
          ]}
          value={filters.actionStatus}
          onChange={(event) => setFilters({ ...filters, actionStatus: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Governing risk"
          options={RISKS.map((risk) => ({ value: risk, label: RISK_LABELS[risk] }))}
          value={filters.governingRisk}
          onChange={(event) => setFilters({ ...filters, governingRisk: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Has scenario risk"
          options={RISKS.map((risk) => ({ value: risk, label: RISK_LABELS[risk] }))}
          value={filters.scenarioRisk}
          onChange={(event) => setFilters({ ...filters, scenarioRisk: event.target.value })}
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
          label="Process node"
          options={(options.data?.processNodes ?? []).map((n) => ({ value: String(n.id), label: n.name }))}
          value={filters.node}
          onChange={(event) => setFilters({ ...filters, node: event.target.value })}
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
          label="Include"
          placeholder="Official only"
          options={[
            { value: "drafts", label: "Drafts too" },
            { value: "archived", label: "Archived too" },
          ]}
          value={filters.drafts ? "drafts" : filters.archived ? "archived" : ""}
          onChange={(event) =>
            setFilters({ ...filters, drafts: event.target.value === "drafts", archived: event.target.value === "archived" })
          }
          className="pointer-coarse:h-11"
        />
      </DashboardToolbar>
      <ActiveFilters chips={chips} onClearAll={clear} />
      {register.isError ? (
        <PsmError error={register.error} onRetry={() => void register.refetch()} />
      ) : register.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading recommendations…</p>
      ) : data && data.rows.length === 0 ? (
        <NoPsmData
          filtered={filtered}
          action={
            filtered ? (
              <Button variant="outline" size="sm" onClick={clear}>
                Clear filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        data && (
          <TableSection
            id="psm-register"
            title="Recommendations"
            description={`${data.total.toLocaleString("en-US")} ${data.total === 1 ? "recommendation" : "recommendations"}. Select a row to see it, then View to open it.`}
          >
            <RegisterTable
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
              noun={["recommendation", "recommendations"]}
              onPage={(page) => setQuery({ ...filters, page })}
            />
          </TableSection>
        )
      )}
      {selected && (
        <ContextPanel
          title={`${selected.displayId} · ${selected.areaEquipment}`}
          description={<span className="line-clamp-3">{selected.recommendationText}</span>}
          details={[
            { label: "Governing risk", value: <RiskBadge risk={selected.governingRisk} /> },
            { label: "Scenarios", value: selected.scenarioCount },
            { label: "Disposition", value: <DispositionBadge disposition={selected.disposition} /> },
            { label: "Action", value: <ActionStatusBadge status={selected.actionStatus} /> },
          ]}
          viewHref={recommendationHref(selected.id)}
          viewLabel="View recommendation"
          onClear={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function filterChips(
  filters: RegisterQuery,
  options: PsmOptions | undefined,
  fixed: string,
  set: (patch: Partial<RegisterQuery>) => void,
): FilterChip[] {
  const chips: FilterChip[] = [];
  const add = (key: string, label: string, reset: Partial<RegisterQuery>) => chips.push({ key, label, onRemove: () => set(reset) });
  const name = (list: { id: number; name: string }[] | undefined, id: string) =>
    list?.find((item) => String(item.id) === id)?.name ?? id;
  if (filters.studyId && !fixed) add("study", `Study: ${name(options?.studies, filters.studyId)}`, { studyId: "" });
  if (filters.q.trim()) add("q", `Search: “${filters.q.trim()}”`, { q: "" });
  if (filters.disposition) add("disposition", `Disposition: ${DISPOSITION_LABELS[filters.disposition] ?? filters.disposition}`, { disposition: "" });
  if (filters.actionStatus)
    add("actionStatus", `Action: ${filters.actionStatus === "none" ? "No action" : (ACTION_STATUS_LABELS[filters.actionStatus] ?? filters.actionStatus)}`, { actionStatus: "" });
  if (filters.governingRisk) add("governingRisk", `Governing risk: ${RISK_LABELS[filters.governingRisk] ?? filters.governingRisk}`, { governingRisk: "" });
  if (filters.scenarioRisk) add("scenarioRisk", `Has a ${RISK_LABELS[filters.scenarioRisk] ?? filters.scenarioRisk} scenario`, { scenarioRisk: "" });
  if (filters.department)
    add("department", `Department: ${filters.department === "unassigned" ? "Unassigned" : name(options?.departments, filters.department)}`, { department: "" });
  if (filters.owner)
    add("owner", `Owner: ${filters.owner === "unassigned" ? "Unassigned" : (options?.owners.find((o) => o.code === filters.owner)?.label ?? filters.owner)}`, { owner: "" });
  if (filters.node) add("node", `Node: ${name(options?.processNodes, filters.node)}`, { node: "" });
  if (filters.equipment) add("equipment", `Equipment: ${filters.equipment}`, { equipment: "" });
  if (filters.dueState) add("dueState", `Due: ${DUE_STATE_LABELS[filters.dueState] ?? filters.dueState}`, { dueState: "" });
  if (filters.stage) add("stage", `Stage reached: ${STAGE_LABELS[filters.stage] ?? filters.stage}`, { stage: "" });
  if (filters.matrixRisk || filters.matrixColumn)
    add(
      "matrix",
      `Matrix: ${RISK_LABELS[filters.matrixRisk] ?? "Any risk"} × ${MATRIX_LABELS[filters.matrixColumn] ?? "any status"}`,
      { matrixRisk: "", matrixColumn: "" },
    );
  if (filters.overdue) add("overdue", "Overdue", { overdue: false });
  if (filters.unassigned) add("unassigned", "No owner", { unassigned: false });
  if (filters.missingDueDate) add("missingDueDate", "No due date", { missingDueDate: false });
  if (filters.drafts) add("drafts", "Including drafts", { drafts: false });
  if (filters.archived) add("archived", "Including archived", { archived: false });
  return chips;
}

const SORTABLE: [string, string][] = [
  ["ID", "id"],
  ["Area / Equipment", "equipment"],
  ["Recommendation", "recommendation"],
  ["Scenarios", "scenarioCount"],
  ["Governing risk", "governingRisk"],
  ["Process node", "node"],
  ["Disposition", "disposition"],
  ["Department", "department"],
  ["Owner", "owner"],
  ["Due date", "dueDate"],
  ["Action status", "actionStatus"],
];

export function RegisterTable({
  rows,
  query,
  selectedId,
  onSelect,
  onSort,
}: {
  rows: RecommendationRow[];
  query: Pick<RegisterQuery, "sort" | "desc">;
  selectedId: number | null;
  onSelect: (row: RecommendationRow) => void;
  onSort: (sort: string, desc: boolean) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1300px] text-left text-sm">
        <caption className="sr-only">PHA recommendations</caption>
        <thead className="border-b bg-muted/30">
          <tr>
            {SORTABLE.map(([label, column]) => (
              <SortHeader key={column} label={label} column={column} sort={query.sort} desc={query.desc} onSort={onSort} className={TH} />
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const active = row.id === selectedId;
            return (
              <tr key={row.id} aria-selected={active} onClick={() => onSelect(row)} className={SELECT_ROW}>
                <td className={cn(TD, "whitespace-nowrap")}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(row);
                    }}
                    className="font-medium rounded-sm focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                    aria-label={`Select ${row.displayId}`}
                  >
                    {row.displayId}
                  </button>
                  <span className="mt-0.5 flex gap-1">
                    {row.isDraft && <StatusBadge tone="neutral">Draft</StatusBadge>}
                    {row.archived && <StatusBadge tone="neutral">Archived</StatusBadge>}
                  </span>
                </td>
                <td className={cn(TD, "max-w-48")}>
                  <span className="line-clamp-2">{row.areaEquipment}</span>
                </td>
                <th scope="row" className={cn(TD, "max-w-96 min-w-72 font-normal")}>
                  <span className="line-clamp-2" title={row.recommendationText}>
                    {row.recommendationText}
                  </span>
                </th>
                <td className={cn(TD, "whitespace-nowrap tabular-nums")}>
                  {row.scenarioCount}
                  <span className="ml-1 text-xs text-muted-foreground">
                    {RISKS.filter((risk) => row.scenarioRisks[risk])
                      .map((risk) => `${row.scenarioRisks[risk]} ${RISK_LABELS[risk]}`)
                      .join(" · ")}
                  </span>
                </td>
                <td className={TD}>
                  <RiskBadge risk={row.governingRisk} />
                </td>
                <td className={cn(TD, "max-w-48 min-w-40")}>
                  <span className="line-clamp-2">{row.processNode ?? <NotEntered label="—" />}</span>
                </td>
                <td className={TD}>
                  <DispositionBadge disposition={row.disposition} />
                </td>
                <td className={TD}>{row.department ?? <NotEntered label="—" />}</td>
                <td className={cn(TD, "whitespace-nowrap")}>{row.owner ?? <NotEntered label="—" />}</td>
                <td className={cn(TD, "whitespace-nowrap")}>
                  {row.dueDate ? formatDate(row.dueDate) : <NotEntered label="—" />}
                </td>
                <td className={TD}>
                  <span className="flex flex-wrap items-center gap-1">
                    <ActionStatusBadge status={row.actionStatus} />
                    <DueStateBadge state={row.actionStatus ? row.dueState : null} />
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Studies({ abilities, options }: { abilities: PsmOptions["abilities"] | undefined; options: PsmOptions | undefined }) {
  const studies = useStudies();
  const [selected, setSelected] = useState<Study | null>(null);
  const [creating, setCreating] = useState(false);
  if (studies.isError) return <PsmError error={studies.error} onRetry={() => void studies.refetch()} />;
  const list = studies.data ?? [];
  return (
    <TableSection
      id="psm-studies"
      title="PHA studies"
      description={studies.isPending ? "Loading…" : `${list.length} ${list.length === 1 ? "study" : "studies"}. Select a study, then View to open it.`}
      actions={
        abilities?.manageStudies ? (
          <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
            <Plus />
            New study
          </Button>
        ) : undefined
      }
    >
      {list.length === 0 && !studies.isPending ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">
          No studies yet. A study is created when a reviewed PHA workbook is imported, or entered here.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm tabular-nums">
            <caption className="sr-only">PHA studies</caption>
            <thead className="border-b bg-muted/30">
              <tr>
                {["Study", "Type", "Year", "Areas", "Recommendations", "Scenarios", "Pending review", "Open actions", "Overdue", "Closed"].map((h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((study) => {
                const active = selected?.id === study.id;
                const c = study.counts;
                return (
                  <tr key={study.id} aria-selected={active} onClick={() => setSelected(active ? null : study)} className={SELECT_ROW}>
                    <th scope="row" className={cn(TD, "font-medium")}>
                      <button
                        type="button"
                        aria-pressed={active}
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelected(active ? null : study);
                        }}
                        className="rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                      >
                        {study.title}
                      </button>
                      <span className="block text-xs font-normal text-muted-foreground">
                        {study.studyCode}
                        {study.imported ? " · imported" : ""}
                      </span>
                    </th>
                    <td className={TD}>{study.studyType}</td>
                    <td className={TD}>{study.year}</td>
                    <td className={TD}>{study.areas.map((a) => a.name).join(", ") || <NotEntered label="—" />}</td>
                    <td className={TD}>{c.recommendations}</td>
                    <td className={TD}>{c.scenarios}</td>
                    <td className={TD}>{c.pending}</td>
                    <td className={TD}>{c.openActions}</td>
                    <td className={TD}>{c.overdue}</td>
                    <td className={TD}>{c.closed}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {selected && (
        <div className="border-t p-3">
          <ContextPanel
            title={selected.title}
            description={`${selected.studyCode} · ${selected.studyType} · ${selected.year}`}
            details={[
              { label: "Recommendations", value: selected.counts.recommendations },
              { label: "Scenarios", value: selected.counts.scenarios },
              { label: "Pending review", value: selected.counts.pending },
              { label: "Open actions", value: selected.counts.openActions },
            ]}
            viewHref={studyHref(selected.id)}
            viewLabel="View study"
            onClear={() => setSelected(null)}
          />
        </div>
      )}
      {creating && options && <StudyDialog options={options} study={null} onClose={() => setCreating(false)} />}
    </TableSection>
  );
}
