"use client";

import { ArchiveRestore, ArrowDown, ArrowLeft, ArrowUp, Check, ChevronRight, History, Pencil, Plus, X } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { TableSection } from "@/features/quality/cost/cost-shared";
import { formatDate, formatTimestamp } from "@/features/quality/cost/format";
import { Field, fieldClasses, inputClasses } from "@/features/quality/cost/record-form";
import { cn } from "@/lib/utils";

import {
  actionHref,
  psmApi,
  RISK_LABELS,
  studyHref,
  type PsmOptions,
  type RecommendationDetail,
  type Scenario,
} from "./api";
import { AssignmentFields, assignmentBody, assignmentProblem, EMPTY_ASSIGNMENT } from "./assignment-fields";
import { EvidenceSection } from "./evidence";
import {
  ActionStatusBadge,
  AttentionBadges,
  Detail,
  DispositionBadge,
  DueStateBadge,
  EYEBROW,
  FormError,
  PsmError,
  ReasonDialog,
  RiskBadge,
} from "./psm-shared";
import { NodeSelect, ScenarioFieldsForm, scenarioBody, scenarioComplete, scenarioDraftOf, EMPTY_SCENARIO, type ScenarioDraft } from "./scenario-fields";
import { usePsmMutation, usePsmOptions, useRecommendation, useTimeline } from "./use-psm";

const MIN_JUSTIFICATION = 20;

export function BackToPha() {
  return (
    <Link href="/safety/psm/pha" className={buttonVariants({ variant: "ghost", size: "sm" })}>
      <ArrowLeft />
      PHA Management
    </Link>
  );
}

/** The recommendation case file: its scenarios, disposition, action, evidence and history. */
export function RecommendationPage({ id }: { id: number }) {
  const rec = useRecommendation(id);
  const options = usePsmOptions();
  if (rec.isError || options.isError) {
    return (
      <div className="space-y-5">
        <BackToPha />
        <PsmError error={rec.error ?? options.error} onRetry={() => void rec.refetch()} />
      </div>
    );
  }
  if (!rec.data || !options.data) return <p className="py-6 text-sm text-muted-foreground">Loading recommendation…</p>;
  return <CaseFile rec={rec.data} options={options.data} />;
}

type Dialogs = "edit" | "accept" | "reject" | "pending" | "archive" | "restore" | "add-scenario" | null;

function CaseFile({ rec, options }: { rec: RecommendationDetail; options: PsmOptions }) {
  const [dialog, setDialog] = useState<Dialogs>(null);
  const [editingScenario, setEditingScenario] = useState<Scenario | null>(null);
  const a = rec.abilities;
  const archived = rec.archivedAt !== null;
  const canEdit = a.editRecommendation && !archived;
  const canDecide = a.decideDisposition && !archived && !rec.isDraft;
  const close = () => setDialog(null);
  const reorder = usePsmMutation((ids: number[]) => psmApi.reorderScenarios(rec.id, { version: rec.version, scenarioIds: ids }));

  const move = (index: number, step: number) => {
    const ids = rec.scenarios.map((s) => s.id);
    const target = index + step;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorder.mutate(ids);
  };

  return (
    <div className="space-y-5">
      <BackToPha />
      <PageHeader
        eyebrow={EYEBROW}
        title={`${rec.displayId} · ${rec.areaEquipment}`}
        status={
          <span className="flex flex-wrap gap-2">
            <DispositionBadge disposition={rec.disposition} />
            <RiskBadge risk={rec.governingRisk} />
            {rec.action && <ActionStatusBadge status={rec.action.status} />}
            {rec.isDraft && <StatusBadge tone="neutral">Draft</StatusBadge>}
            {archived && <StatusBadge tone="neutral">Archived</StatusBadge>}
          </span>
        }
        actions={
          <>
            {canEdit && (
              <Button variant="outline" size="sm" onClick={() => setDialog("edit")}>
                <Pencil />
                Edit
              </Button>
            )}
            {a.editRecommendation && !archived && (
              <Button variant="ghost" size="sm" onClick={() => setDialog("archive")}>
                Archive
              </Button>
            )}
            {a.editRecommendation && archived && (
              <Button variant="outline" size="sm" onClick={() => setDialog("restore")}>
                <ArchiveRestore />
                Restore
              </Button>
            )}
          </>
        }
      />
      {archived && (
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
          Archived {rec.archivedAt ? formatTimestamp(rec.archivedAt) : ""}. Reason: {rec.archiveReason}
        </p>
      )}
      {rec.isDraft && (
        <p className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm">
          Draft: not counted in figures and no disposition can be decided until it is finalized with at least one scenario.
        </p>
      )}

      <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-5">
        <h2 className="text-base font-semibold">Recommendation</h2>
        <p className="text-sm whitespace-pre-wrap">{rec.recommendationText}</p>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Detail label="Study">
            <Link href={studyHref(rec.study.id)} className="text-primary hover:underline">
              {rec.study.title}
            </Link>
          </Detail>
          <Detail label="Area / equipment">{rec.areaEquipment}</Detail>
          <Detail label="Process node">{rec.processNode}</Detail>
          <Detail label="Governing risk">
            <RiskBadge risk={rec.governingRisk} />
          </Detail>
          <Detail label="Recommendation number">{rec.recommendationNumber}</Detail>
          <Detail label="Scenarios">{rec.scenarios.length}</Detail>
          {rec.sourceRowStart !== null && (
            <Detail label="Source">
              {rec.study.sourceSheetName ? `Sheet “${rec.study.sourceSheetName}”, ` : ""}
              {rec.sourceRowEnd !== rec.sourceRowStart ? `rows ${rec.sourceRowStart}–${rec.sourceRowEnd}` : `row ${rec.sourceRowStart}`}
            </Detail>
          )}
          <Detail label={rec.sourceRowStart !== null ? "Imported" : "Created"}>{formatTimestamp(rec.createdAt)}</Detail>
          <Detail label="Last updated">{formatTimestamp(rec.updatedAt)}</Detail>
          {rec.notes && (
            <Detail label="Notes" className="col-span-2 sm:col-span-4">
              <span className="whitespace-pre-wrap">{rec.notes}</span>
            </Detail>
          )}
        </dl>
      </section>

      <ScenarioList
        scenarios={rec.scenarios}
        canEdit={canEdit}
        reordering={reorder.isPending}
        reorderError={reorder.error}
        onMove={move}
        onEdit={setEditingScenario}
        onAdd={() => setDialog("add-scenario")}
      />

      <DispositionSection rec={rec} canDecide={canDecide} onOpen={setDialog} />
      <ActionSummary rec={rec} />
      <EvidenceSection
        target={{ recommendationId: rec.id }}
        attachments={rec.attachments}
        evidenceTypes={options.evidenceTypes}
        canUpload={(a.editRecommendation || a.manageActions || a.requestClosure) && !archived}
        canRemove={a.editRecommendation || a.manageActions || a.requestClosure}
      />
      <TimelineSection id={rec.id} />

      {dialog === "edit" && <EditDialog rec={rec} options={options} onClose={close} />}
      {dialog === "add-scenario" && <ScenarioDialog rec={rec} scenario={null} options={options} onClose={close} />}
      {editingScenario && <ScenarioDialog rec={rec} scenario={editingScenario} options={options} onClose={() => setEditingScenario(null)} />}
      {dialog === "accept" && <AcceptDialog rec={rec} options={options} onClose={close} />}
      {dialog === "reject" && <RejectDialog rec={rec} onClose={close} />}
      {dialog === "pending" && (
        <RecommendationReason
          rec={rec}
          title="Return to Pending Review"
          description="Undo a disposition decided in error. Only possible while no action exists."
          confirmLabel="Return to Pending Review"
          run={(reason) => psmApi.returnToPending(rec.id, { version: rec.version, reason })}
          onClose={close}
        />
      )}
      {dialog === "archive" && (
        <RecommendationReason
          rec={rec}
          title={`Archive ${rec.displayId}`}
          description="Archived recommendations leave the register and figures. Nothing is deleted; it can be restored. Not possible while its action is open."
          confirmLabel="Archive"
          run={(reason) => psmApi.archive(rec.id, { version: rec.version, reason })}
          onClose={close}
        />
      )}
      {dialog === "restore" && (
        <RecommendationReason
          rec={rec}
          title={`Restore ${rec.displayId}`}
          confirmLabel="Restore"
          run={(reason) => psmApi.restore(rec.id, { version: rec.version, reason })}
          onClose={close}
        />
      )}
    </div>
  );
}

function DispositionSection({ rec, canDecide, onOpen }: { rec: RecommendationDetail; canDecide: boolean; onOpen: (d: Dialogs) => void }) {
  return (
    <section className="space-y-3 rounded-lg border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Disposition</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            The review decision. It is kept separate from the action&apos;s status.
          </p>
        </div>
        {canDecide && (
          <div className="flex flex-wrap gap-2">
            {rec.disposition !== "accepted" && (
              <Button size="sm" onClick={() => onOpen("accept")}>
                <Check />
                Accept
              </Button>
            )}
            {rec.disposition !== "rejected" && (
              <Button variant="outline" size="sm" onClick={() => onOpen("reject")}>
                <X />
                Reject
              </Button>
            )}
            {rec.disposition !== "pending_review" && rec.action === null && (
              <Button variant="ghost" size="sm" onClick={() => onOpen("pending")}>
                Return to Pending Review
              </Button>
            )}
          </div>
        )}
      </header>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Detail label="Disposition">
          <DispositionBadge disposition={rec.disposition} />
        </Detail>
        <Detail label="Decided by">{rec.dispositionByName}</Detail>
        <Detail label="Decided">{rec.dispositionAt ? formatTimestamp(rec.dispositionAt) : null}</Detail>
        {rec.dispositionJustification && (
          <Detail
            label={rec.disposition === "rejected" ? "Rejection justification" : "Earlier rejection justification"}
            className="col-span-2 sm:col-span-4"
          >
            <span className="whitespace-pre-wrap">{rec.dispositionJustification}</span>
          </Detail>
        )}
      </dl>
    </section>
  );
}

/** Each hazard scenario as its own collapsible card, in workbook order. */
function ScenarioList({
  scenarios,
  canEdit,
  reordering,
  reorderError,
  onMove,
  onEdit,
  onAdd,
}: {
  scenarios: Scenario[];
  canEdit: boolean;
  reordering: boolean;
  reorderError: unknown;
  onMove: (index: number, step: number) => void;
  onEdit: (scenario: Scenario) => void;
  onAdd: () => void;
}) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(() => new Set());
  const toggle = (id: number) =>
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allCollapsed = scenarios.every((s) => collapsed.has(s.id));
  return (
    <section aria-labelledby="psm-scenarios" className="space-y-3 rounded-lg border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="psm-scenarios" className="text-base font-semibold">
            Hazard scenarios ({scenarios.length})
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Each scenario is kept separately, in workbook order. The governing risk is the highest risk among them.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {scenarios.length > 1 && (
            <>
              <Button variant="ghost" size="sm" disabled={collapsed.size === 0} onClick={() => setCollapsed(new Set())}>
                Expand all
              </Button>
              <Button variant="ghost" size="sm" disabled={allCollapsed} onClick={() => setCollapsed(new Set(scenarios.map((s) => s.id)))}>
                Collapse all
              </Button>
            </>
          )}
          {canEdit && (
            <Button variant="outline" size="sm" onClick={onAdd}>
              <Plus />
              Add scenario
            </Button>
          )}
        </div>
      </header>
      {scenarios.length === 0 ? (
        <p className="text-sm text-muted-foreground">No scenarios recorded.</p>
      ) : (
        <ol className="space-y-3">
          {scenarios.map((s, index) => {
            const open = !collapsed.has(s.id);
            const number = String(index + 1).padStart(2, "0");
            const bodyId = `psm-scenario-${s.id}`;
            return (
              <li key={s.id} className="rounded-md border">
                <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={bodyId}
                    onClick={() => toggle(s.id)}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded-sm py-1 text-left text-sm font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    <ChevronRight aria-hidden className={cn("size-4 shrink-0 transition-transform", open && "rotate-90")} />
                    <span className="shrink-0">Scenario {number}</span>
                    {!open && <span className="min-w-0 truncate font-normal text-muted-foreground">{s.event}</span>}
                  </button>
                  <RiskBadge risk={s.risk} />
                  {canEdit && (
                    <span className="flex gap-1">
                      <Button variant="ghost" size="sm" aria-label={`Move scenario ${index + 1} up`} disabled={index === 0 || reordering} onClick={() => onMove(index, -1)}>
                        <ArrowUp />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Move scenario ${index + 1} down`}
                        disabled={index === scenarios.length - 1 || reordering}
                        onClick={() => onMove(index, 1)}
                      >
                        <ArrowDown />
                      </Button>
                      <Button variant="ghost" size="sm" aria-label={`Edit scenario ${index + 1}`} onClick={() => onEdit(s)}>
                        <Pencil />
                      </Button>
                    </span>
                  )}
                </div>
                <dl id={bodyId} hidden={!open} className={cn("grid gap-4 border-t px-3 py-3 lg:grid-cols-3", !open && "hidden")}>
                  <Detail label="Event">
                    <span className="whitespace-pre-wrap">{s.event}</span>
                  </Detail>
                  <Detail label="Cause">
                    <span className="whitespace-pre-wrap">{s.cause}</span>
                  </Detail>
                  <Detail label="Consequence">
                    <span className="whitespace-pre-wrap">{s.consequence}</span>
                  </Detail>
                  <Detail label="Risk">
                    <RiskBadge risk={s.risk} />
                    {s.riskSource && s.riskSource.trim().toLowerCase() !== RISK_LABELS[s.risk]?.toLowerCase() && (
                      <span className="mt-1 block text-xs text-muted-foreground">Recorded as “{s.riskSource}”</span>
                    )}
                  </Detail>
                  <Detail label="Area / equipment">{s.areaEquipment}</Detail>
                  <Detail label="Process node">{s.processNode}</Detail>
                </dl>
              </li>
            );
          })}
        </ol>
      )}
      {reorderError ? <FormError error={reorderError} /> : null}
    </section>
  );
}

function ActionSummary({ rec }: { rec: RecommendationDetail }) {
  const action = rec.action;
  return (
    <section className="space-y-3 rounded-lg border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Action</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {action ? "Generated when the recommendation was accepted. One action per recommendation." : "An action is generated when the recommendation is accepted."}
          </p>
        </div>
        {action && (
          <Link href={actionHref(action.id)} className={buttonVariants({ size: "sm" })}>
            View action
          </Link>
        )}
      </header>
      {action ? (
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Detail label="Action">{action.actionNumber}</Detail>
          <Detail label="Status">
            <span className="flex flex-wrap gap-1">
              <ActionStatusBadge status={action.status} />
              <DueStateBadge state={action.dueState} />
            </span>
          </Detail>
          <Detail label="Owner">
            {action.ownerName || action.ownerEmail ? (
              <>
                {action.ownerName}
                {action.ownerEmail && <span className="block text-xs text-muted-foreground">{action.ownerEmail}</span>}
              </>
            ) : null}
          </Detail>
          <Detail label="Department">{action.department}</Detail>
          <Detail label="Due date">{action.dueDate ? formatDate(action.dueDate) : null}</Detail>
          {action.attention.length > 0 && (
            <Detail label="Needs attention" className="col-span-2 sm:col-span-3">
              <AttentionBadges reasons={action.attention} />
            </Detail>
          )}
        </dl>
      ) : (
        <p className="text-sm text-muted-foreground">No action.</p>
      )}
    </section>
  );
}

function RecommendationReason({
  rec,
  title,
  description,
  confirmLabel,
  run,
  onClose,
}: {
  rec: RecommendationDetail;
  title: string;
  description?: string;
  confirmLabel: string;
  run: (reason: string) => Promise<RecommendationDetail>;
  onClose: () => void;
}) {
  const mutation = usePsmMutation(run);
  return (
    <ReasonDialog
      open
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      pending={mutation.isPending}
      error={mutation.error}
      onClose={onClose}
      onConfirm={(reason) =>
        mutation.mutate(reason, {
          onSuccess: () => {
            toast("success", `${rec.displayId} saved`);
            onClose();
          },
        })
      }
    />
  );
}

function AcceptDialog({ rec, options, onClose }: { rec: RecommendationDetail; options: PsmOptions; onClose: () => void }) {
  const id = useId();
  const [assignment, setAssignment] = useState(EMPTY_ASSIGNMENT);
  const accept = usePsmMutation((body: Parameters<typeof psmApi.accept>[1]) => psmApi.accept(rec.id, body));
  const canAssign = rec.abilities.manageActions;
  const problem = canAssign ? assignmentProblem(assignment) : null;
  const reaccept = rec.action !== null;
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Accept ${rec.displayId}`}
      description={
        reaccept
          ? "The action kept from the earlier acceptance is reinstated. No second action is created."
          : "Accepting generates one action for this recommendation. Accepting again never creates a second one."
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={accept.isPending || problem !== null}
            onClick={() =>
              accept.mutate(
                { version: rec.version, confirm: true, ...(canAssign ? assignmentBody(assignment) : {}) },
                {
                  onSuccess: (saved) => {
                    toast("success", `${rec.displayId} accepted`, saved.action ? `Action ${saved.action.actionNumber}` : undefined);
                    onClose();
                  },
                },
              )
            }
          >
            {accept.isPending ? "Accepting…" : "Accept recommendation"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {canAssign ? (
          <>
            <p className="text-sm text-muted-foreground">Assignment is optional now; it can be completed on the action later.</p>
            <AssignmentFields id={id} draft={assignment} departments={options.departments} onChange={setAssignment} />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">The action will be created without an owner; someone who manages actions assigns it.</p>
        )}
        {problem && <p className="text-sm text-destructive">{problem}</p>}
        <FormError error={accept.error} />
      </div>
    </Dialog>
  );
}

function RejectDialog({ rec, onClose }: { rec: RecommendationDetail; onClose: () => void }) {
  const id = useId();
  const [justification, setJustification] = useState(rec.dispositionJustification ?? "");
  const reject = usePsmMutation((text: string) => psmApi.reject(rec.id, { version: rec.version, justification: text }));
  const short = justification.trim().length < MIN_JUSTIFICATION;
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Reject ${rec.displayId}`}
      description={
        rec.action
          ? "The existing action is kept and flagged for a PSM administrator to resolve. Nothing is deleted."
          : "The justification is kept permanently with the recommendation."
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={short || reject.isPending}
            onClick={() =>
              reject.mutate(justification.trim(), {
                onSuccess: () => {
                  toast("success", `${rec.displayId} rejected`);
                  onClose();
                },
              })
            }
          >
            {reject.isPending ? "Saving…" : "Reject recommendation"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <Field id={`${id}-justification`} label="Justification" required hint={`Why the recommendation is not being implemented (at least ${MIN_JUSTIFICATION} characters).`}>
          <textarea
            id={`${id}-justification`}
            rows={5}
            value={justification}
            maxLength={8000}
            onChange={(e) => setJustification(e.target.value)}
            className={cn(fieldClasses, "py-2")}
          />
        </Field>
        <FormError error={reject.error} />
      </div>
    </Dialog>
  );
}

function EditDialog({ rec, options, onClose }: { rec: RecommendationDetail; options: PsmOptions; onClose: () => void }) {
  const id = useId();
  const [draft, setDraft] = useState({
    areaEquipment: rec.areaEquipment,
    recommendationText: rec.recommendationText,
    processNodeId: rec.processNodeId ? String(rec.processNodeId) : "",
    notes: rec.notes ?? "",
    isDraft: rec.isDraft,
  });
  const save = usePsmMutation(() =>
    psmApi.updateRecommendation(rec.id, {
      version: rec.version,
      areaEquipment: draft.areaEquipment.trim(),
      recommendationText: draft.recommendationText.trim(),
      processNodeId: draft.processNodeId ? Number(draft.processNodeId) : null,
      notes: draft.notes.trim() || null,
      isDraft: draft.isDraft,
    }),
  );
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Edit ${rec.displayId}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!draft.areaEquipment.trim() || !draft.recommendationText.trim() || save.isPending}
            onClick={() => save.mutate(undefined, { onSuccess: () => (toast("success", `${rec.displayId} saved`), onClose()) })}
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id={`${id}-equipment`} label="Area / equipment" required>
          <input id={`${id}-equipment`} value={draft.areaEquipment} maxLength={200} onChange={(e) => setDraft({ ...draft, areaEquipment: e.target.value })} className={inputClasses} />
        </Field>
        <Field id={`${id}-node`} label="Process node">
          <NodeSelect id={`${id}-node`} value={draft.processNodeId} nodes={options.processNodes} canAdd onChange={(processNodeId) => setDraft({ ...draft, processNodeId })} />
        </Field>
        <Field id={`${id}-text`} label="Recommendation" required className="sm:col-span-2">
          <textarea
            id={`${id}-text`}
            rows={5}
            value={draft.recommendationText}
            maxLength={8000}
            onChange={(e) => setDraft({ ...draft, recommendationText: e.target.value })}
            className={cn(fieldClasses, "py-2")}
          />
        </Field>
        <Field id={`${id}-notes`} label="Notes" className="sm:col-span-2">
          <textarea id={`${id}-notes`} rows={3} value={draft.notes} maxLength={8000} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} className={cn(fieldClasses, "py-2")} />
        </Field>
        {rec.disposition === "pending_review" && (
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" checked={draft.isDraft} onChange={(e) => setDraft({ ...draft, isDraft: e.target.checked })} />
            Draft (left out of figures; needs at least one scenario to be finalized)
          </label>
        )}
        <div className="sm:col-span-2">
          <FormError error={save.error} />
        </div>
      </div>
    </Dialog>
  );
}

function ScenarioDialog({
  rec,
  scenario,
  options,
  onClose,
}: {
  rec: RecommendationDetail;
  scenario: Scenario | null;
  options: PsmOptions;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<ScenarioDraft>(scenario ? scenarioDraftOf(scenario) : EMPTY_SCENARIO);
  const save = usePsmMutation((d: ScenarioDraft) =>
    scenario
      ? psmApi.updateScenario(rec.id, scenario.id, { ...scenarioBody(d), version: scenario.version })
      : psmApi.addScenario(rec.id, scenarioBody(d)),
  );
  return (
    <Dialog
      open
      onClose={onClose}
      title={scenario ? `Edit scenario ${scenario.sequenceNumber}` : "Add a hazard scenario"}
      description="Only this scenario changes; the others are kept as they are."
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!scenarioComplete(draft) || save.isPending} onClick={() => save.mutate(draft, { onSuccess: onClose })}>
            {save.isPending ? "Saving…" : "Save scenario"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <ScenarioFieldsForm draft={draft} nodes={options.processNodes} canAddNode={rec.abilities.editRecommendation} onChange={setDraft} />
        <FormError error={save.error} />
      </div>
    </Dialog>
  );
}

const EVENT_LABELS: Record<string, string> = {
  created: "Created",
  imported: "Imported from the PHA workbook",
  edited: "Edited",
  scenario_added: "Scenario added",
  scenario_edited: "Scenario edited",
  scenarios_reordered: "Scenarios reordered",
  disposition_changed: "Disposition changed",
  rejection_justification_added: "Rejection justification added",
  rejection_justification_changed: "Rejection justification changed",
  flagged_for_resolution: "Action flagged for resolution",
  action_generated: "Action generated",
  action_reinstated: "Action reinstated",
  task_changed: "Task changed",
  department_changed: "Department changed",
  owner_changed: "Owner changed",
  due_date_changed: "Due date changed",
  status_changed: "Status changed",
  closure_requested: "Closure requested",
  closure_verified: "Closure verified",
  closed: "Closed",
  returned: "Returned to In Progress",
  reopened: "Reopened",
  comment_added: "Comment added",
  resolution_recorded: "Resolution recorded",
  evidence_added: "Evidence added",
  evidence_removed: "Evidence removed",
  archived: "Archived",
  restored: "Restored",
};

function describeValues(value: Record<string, unknown> | null): string {
  if (!value) return "";
  return Object.entries(value)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

function TimelineSection({ id }: { id: number }) {
  const [open, setOpen] = useState(false);
  const timeline = useTimeline(id, open);
  return (
    <TableSection
      id="psm-timeline"
      title="History"
      description="Every recorded change to the recommendation, its scenarios, action and evidence."
      actions={
        <Button variant="outline" size="sm" onClick={() => setOpen(!open)} aria-expanded={open}>
          <History />
          {open ? "Hide history" : "Show history"}
        </Button>
      }
    >
      {open &&
        (timeline.isError ? (
          <div className="p-3">
            <FormError error={timeline.error} />
          </div>
        ) : !timeline.data ? (
          <p className="px-4 py-3 text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ol className="divide-y">
            {timeline.data.map((event, index) => {
              const from = describeValues(event.oldValue);
              const to = describeValues(event.newValue);
              return (
                <li key={index} className="px-4 py-2 text-sm">
                  <p>
                    <span className="font-medium">{EVENT_LABELS[event.event] ?? event.event}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      · {event.entity} · {event.actorName} · {formatTimestamp(event.occurredAt)}
                    </span>
                  </p>
                  {(from || to) && (
                    <p className="mt-0.5 text-xs break-words text-muted-foreground">
                      {from && <span className="block">From {from}</span>}
                      {to && <span className="block">To {to}</span>}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        ))}
    </TableSection>
  );
}
