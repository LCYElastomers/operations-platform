"use client";

import { ArrowLeft, Check, Pencil, Play, RotateCcw, Send, Undo2 } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { TableSection } from "@/features/quality/cost/cost-shared";
import { formatDate, formatTimestamp } from "@/features/quality/cost/format";
import { Field, fieldClasses, inputClasses } from "@/features/quality/cost/record-form";
import { cn } from "@/lib/utils";

import {
  ACTION_STATUS_LABELS,
  NOTIFICATION_STATUS_LABELS,
  psmApi,
  recommendationHref,
  type ActionDetail,
  type Notification,
  type PsmOptions,
} from "./api";
import { AssignmentFields, assignmentBody, assignmentOf, assignmentProblem } from "./assignment-fields";
import { EvidenceSection } from "./evidence";
import {
  ActionStatusBadge,
  AttentionBadges,
  Detail,
  DueStateBadge,
  EYEBROW,
  FormError,
  PsmError,
  ReasonDialog,
  RiskBadge,
} from "./psm-shared";
import { useAction, usePsmMutation, usePsmOptions } from "./use-psm";

const MIN_REASON = 10;

function BackToActions() {
  return (
    <Link href="/safety/psm/actions" className={buttonVariants({ variant: "ghost", size: "sm" })}>
      <ArrowLeft />
      Action Items
    </Link>
  );
}

export function ActionPage({ id }: { id: number }) {
  const detail = useAction(id);
  const options = usePsmOptions();
  if (detail.isError || options.isError) {
    return (
      <div className="space-y-5">
        <BackToActions />
        <PsmError error={detail.error ?? options.error} onRetry={() => void detail.refetch()} />
      </div>
    );
  }
  if (!detail.data || !options.data) return <p className="py-6 text-sm text-muted-foreground">Loading action…</p>;
  return <ActionFile detail={detail.data} options={options.data} />;
}

type Dialogs = "edit" | "request" | "approve" | "return" | "reopen" | "resolve" | null;

function ActionFile({ detail, options }: { detail: ActionDetail; options: PsmOptions }) {
  const [dialog, setDialog] = useState<Dialogs>(null);
  const { action, abilities: a } = detail;
  const close = () => setDialog(null);
  const working = action.status === "not_started" || action.status === "in_progress";
  const status = usePsmMutation((next: "not_started" | "in_progress") =>
    psmApi.changeStatus(action.id, { version: action.version, status: next, note: null }),
  );
  const locked =
    action.status === "pending_verification"
      ? "Evidence is locked while closure is being verified."
      : action.status === "closed"
        ? "Evidence is locked: the action is closed. Reopen it to change evidence."
        : undefined;

  return (
    <div className="space-y-5">
      <BackToActions />
      <PageHeader
        eyebrow={EYEBROW}
        title={`${action.actionNumber} · ${action.recommendationDisplayId}`}
        description={action.title}
        status={
          <span className="flex flex-wrap gap-2">
            <ActionStatusBadge status={action.status} />
            <RiskBadge risk={action.governingRisk} />
            <DueStateBadge state={action.dueState} />
            {action.archived && <StatusBadge tone="neutral">Archived</StatusBadge>}
          </span>
        }
        actions={
          <Link href={recommendationHref(action.recommendationId)} className={buttonVariants({ variant: "outline", size: "sm" })}>
            View recommendation
          </Link>
        }
      />

      {action.requiresResolution && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm">
          <p>The recommendation was rejected after this action was generated. A PSM administrator decides whether to keep or archive it.</p>
          {a.admin && (
            <Button size="sm" variant="outline" onClick={() => setDialog("resolve")}>
              Resolve
            </Button>
          )}
        </div>
      )}

      <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-5">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-base font-semibold">Assignment</h2>
          <div className="flex flex-wrap gap-2">
            {a.manageActions && working && !action.archived && (
              <Button variant="outline" size="sm" onClick={() => setDialog("edit")}>
                <Pencil />
                Edit assignment
              </Button>
            )}
            {(a.manageActions || a.requestClosure) && action.status === "not_started" && !action.archived && (
              <Button size="sm" variant="outline" disabled={status.isPending} onClick={() => status.mutate("in_progress")}>
                <Play />
                Start work
              </Button>
            )}
            {(a.manageActions || a.requestClosure) && action.status === "in_progress" && (
              <Button size="sm" variant="ghost" disabled={status.isPending} onClick={() => status.mutate("not_started")}>
                Back to Not Started
              </Button>
            )}
          </div>
        </header>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Detail label="Department">{action.department}</Detail>
          <Detail label="Owner">
            {action.ownerName}
            {action.ownerEmail ? <span className="block text-xs text-muted-foreground">{action.ownerEmail}</span> : null}
          </Detail>
          <Detail label="Due date">{action.dueDate ? formatDate(action.dueDate) : null}</Detail>
          <Detail label="Open for">{action.status === "closed" ? "Closed" : `${action.ageDays} ${action.ageDays === 1 ? "day" : "days"}`}</Detail>
          <Detail label="Task" className="col-span-2 sm:col-span-4">
            {action.description ? <span className="whitespace-pre-wrap">{action.description}</span> : null}
          </Detail>
          <Detail label="Recommendation" className="col-span-2 sm:col-span-4">
            <span className="whitespace-pre-wrap">{action.recommendationText}</span>
          </Detail>
          {action.attention.length > 0 && (
            <Detail label="Needs attention" className="col-span-2 sm:col-span-4">
              <AttentionBadges reasons={action.attention} />
            </Detail>
          )}
        </dl>
        <FormError error={status.error} />
      </section>

      <ClosureSection detail={detail} onOpen={setDialog} />

      <EvidenceSection
        target={{ actionId: action.id }}
        attachments={detail.attachments}
        evidenceTypes={options.evidenceTypes}
        canUpload={(a.manageActions || a.requestClosure || a.editRecommendation) && !action.archived}
        canRemove={a.manageActions || a.requestClosure || a.editRecommendation}
        lockedReason={locked}
      />
      <UpdatesSection detail={detail} />
      <NotificationsSection notifications={detail.notifications} mailEnabled={detail.mailEnabled} />

      {dialog === "edit" && <EditAssignmentDialog detail={detail} options={options} onClose={close} />}
      {dialog === "request" && <RequestClosureDialog detail={detail} onClose={close} />}
      {dialog === "approve" && <ApproveDialog detail={detail} onClose={close} />}
      {dialog === "return" && (
        <ActionReason
          title="Return to In Progress"
          description="The closure is not verified. The owner sees your reason and the action goes back to In Progress."
          confirmLabel="Return closure"
          run={(reason) => psmApi.returnClosure(action.id, { version: action.version, reason })}
          onClose={close}
        />
      )}
      {dialog === "reopen" && (
        <ActionReason
          title={`Reopen ${action.actionNumber}`}
          description="The action goes back to In Progress. Its closure history is kept."
          confirmLabel="Reopen"
          run={(reason) => psmApi.reopen(action.id, { version: action.version, reason })}
          onClose={close}
        />
      )}
      {dialog === "resolve" && <ResolveDialog detail={detail} onClose={close} />}
    </div>
  );
}

function ClosureSection({ detail, onOpen }: { detail: ActionDetail; onOpen: (d: Dialogs) => void }) {
  const { action, abilities: a } = detail;
  const working = action.status === "not_started" || action.status === "in_progress";
  return (
    <section className="space-y-3 rounded-lg border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Closure</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            An action closes only when a closure request with a summary and evidence is verified.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {a.requestClosure && working && !action.archived && (
            <Button size="sm" onClick={() => onOpen("request")}>
              <Send />
              Request closure
            </Button>
          )}
          {a.verifyClosure && action.status === "pending_verification" && (
            <>
              <Button size="sm" onClick={() => onOpen("approve")}>
                <Check />
                Verify and close
              </Button>
              <Button size="sm" variant="outline" onClick={() => onOpen("return")}>
                <Undo2 />
                Return
              </Button>
            </>
          )}
          {a.reopen && action.status === "closed" && (
            <Button size="sm" variant="outline" onClick={() => onOpen("reopen")}>
              <RotateCcw />
              Reopen
            </Button>
          )}
        </div>
      </header>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Detail label="Requested by">{action.closureRequestedByName}</Detail>
        <Detail label="Requested">{action.closureRequestedAt ? formatTimestamp(action.closureRequestedAt) : null}</Detail>
        <Detail label="Verified by">{action.verifiedByName}</Detail>
        <Detail label="Closed">{action.closedAt ? formatTimestamp(action.closedAt) : null}</Detail>
        {action.closureSummary && (
          <Detail label="Closure summary" className="col-span-2 sm:col-span-4">
            <span className="whitespace-pre-wrap">{action.closureSummary}</span>
          </Detail>
        )}
        {action.closureExceptionReason && (
          <Detail label="Documented exception (no evidence)" className="col-span-2 sm:col-span-4">
            <span className="whitespace-pre-wrap">{action.closureExceptionReason}</span>
          </Detail>
        )}
        {action.returnReason && (
          <Detail label={`Last returned${action.returnedAt ? ` ${formatTimestamp(action.returnedAt)}` : ""}`} className="col-span-2">
            <span className="whitespace-pre-wrap">{action.returnReason}</span>
          </Detail>
        )}
        {action.reopenReason && (
          <Detail label={`Last reopened${action.reopenedAt ? ` ${formatTimestamp(action.reopenedAt)}` : ""}`} className="col-span-2">
            <span className="whitespace-pre-wrap">{action.reopenReason}</span>
          </Detail>
        )}
      </dl>
    </section>
  );
}

function ActionReason({
  title,
  description,
  confirmLabel,
  run,
  onClose,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  run: (reason: string) => Promise<ActionDetail>;
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
      onConfirm={(reason) => mutation.mutate(reason, { onSuccess: () => (toast("success", "Saved"), onClose()) })}
    />
  );
}

function EditAssignmentDialog({ detail, options, onClose }: { detail: ActionDetail; options: PsmOptions; onClose: () => void }) {
  const id = useId();
  const { action } = detail;
  const [title, setTitle] = useState(action.title);
  const [draft, setDraft] = useState(() => assignmentOf(action));
  const [dueDateReason, setDueDateReason] = useState("");
  const dueMoved = action.dueDate !== null && (draft.dueDate || null) !== action.dueDate;
  const needsReason = dueMoved && action.status !== "not_started";
  const problem = assignmentProblem(draft) ?? (needsReason && dueDateReason.trim().length < MIN_REASON ? "Give a reason for moving the due date." : null);
  const save = usePsmMutation(() =>
    psmApi.updateAction(action.id, {
      version: action.version,
      title: title.trim(),
      ...assignmentBody(draft),
      dueDateReason: dueMoved ? dueDateReason.trim() || null : null,
    }),
  );
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Edit ${action.actionNumber}`}
      description="Editing never closes an action. The owner is notified of an assignment or due-date change when email is configured."
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!title.trim() || problem !== null || save.isPending}
            onClick={() => save.mutate(undefined, { onSuccess: () => (toast("success", `${action.actionNumber} saved`), onClose()) })}
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Field id={`${id}-title`} label="Title" required>
          <input id={`${id}-title`} value={title} maxLength={500} onChange={(e) => setTitle(e.target.value)} className={inputClasses} />
        </Field>
        <AssignmentFields id={id} draft={draft} departments={options.departments} onChange={setDraft} />
        {needsReason && (
          <Field id={`${id}-due-reason`} label="Reason for moving the due date" required hint={`Work has begun. At least ${MIN_REASON} characters.`}>
            <textarea
              id={`${id}-due-reason`}
              rows={3}
              value={dueDateReason}
              maxLength={8000}
              onChange={(e) => setDueDateReason(e.target.value)}
              className={cn(fieldClasses, "py-2")}
            />
          </Field>
        )}
        {problem && <p className="text-sm text-destructive">{problem}</p>}
        <FormError error={save.error} />
      </div>
    </Dialog>
  );
}

function RequestClosureDialog({ detail, onClose }: { detail: ActionDetail; onClose: () => void }) {
  const id = useId();
  const { action, abilities } = detail;
  const evidence = detail.attachments.filter((x) => !x.removedAt).length;
  const [summary, setSummary] = useState("");
  const [skipReason, setSkipReason] = useState("");
  const [useException, setUseException] = useState(false);
  const [exceptionReason, setExceptionReason] = useState("");
  const skipping = action.status === "not_started";
  const exception = abilities.admin && useException;
  const problem =
    summary.trim().length < MIN_REASON
      ? `Summarize what was done (at least ${MIN_REASON} characters).`
      : skipping && skipReason.trim().length < MIN_REASON
        ? "Explain why the action is ready without having been In Progress."
        : evidence === 0 && !exception
          ? abilities.admin
            ? "Attach evidence first, or document an exception."
            : "Attach evidence first."
          : exception && exceptionReason.trim().length < MIN_REASON
            ? "Document why no evidence is attached."
            : null;
  const request = usePsmMutation(() =>
    psmApi.requestClosure(action.id, {
      version: action.version,
      summary: summary.trim(),
      skipReason: skipping ? skipReason.trim() : null,
      exceptionReason: exception ? exceptionReason.trim() : null,
    }),
  );
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Request closure of ${action.actionNumber}`}
      description={`The action moves to Pending Verification; a verifier approves or returns it. ${evidence} evidence ${evidence === 1 ? "file" : "files"} attached.`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={problem !== null || request.isPending}
            onClick={() => request.mutate(undefined, { onSuccess: () => (toast("success", "Closure requested"), onClose()) })}
          >
            {request.isPending ? "Sending…" : "Request closure"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Field id={`${id}-summary`} label="Closure summary" required hint="What was done to implement the recommendation.">
          <textarea id={`${id}-summary`} rows={4} value={summary} maxLength={8000} onChange={(e) => setSummary(e.target.value)} className={cn(fieldClasses, "py-2")} />
        </Field>
        {skipping && (
          <Field id={`${id}-skip`} label="Why it was never In Progress" required>
            <textarea id={`${id}-skip`} rows={2} value={skipReason} maxLength={8000} onChange={(e) => setSkipReason(e.target.value)} className={cn(fieldClasses, "py-2")} />
          </Field>
        )}
        {abilities.admin && evidence === 0 && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={useException} onChange={(e) => setUseException(e.target.checked)} />
            Request closure without evidence (documented PSM administrator exception)
          </label>
        )}
        {exception && (
          <Field id={`${id}-exception`} label="Why no evidence is attached" required>
            <textarea
              id={`${id}-exception`}
              rows={3}
              value={exceptionReason}
              maxLength={8000}
              onChange={(e) => setExceptionReason(e.target.value)}
              className={cn(fieldClasses, "py-2")}
            />
          </Field>
        )}
        {problem && <p className="text-sm text-muted-foreground">{problem}</p>}
        <FormError error={request.error} />
      </div>
    </Dialog>
  );
}

function ApproveDialog({ detail, onClose }: { detail: ActionDetail; onClose: () => void }) {
  const id = useId();
  const { action } = detail;
  const [note, setNote] = useState("");
  const approve = usePsmMutation(() => psmApi.approveClosure(action.id, { version: action.version, note: note.trim() || null }));
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Verify and close ${action.actionNumber}`}
      description="Confirm the closure summary and evidence show the recommendation was implemented."
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={approve.isPending} onClick={() => approve.mutate(undefined, { onSuccess: () => (toast("success", `${action.actionNumber} closed`), onClose()) })}>
            {approve.isPending ? "Closing…" : "Verify and close"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {action.closureSummary && <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm whitespace-pre-wrap">{action.closureSummary}</p>}
        <Field id={`${id}-note`} label="Verification note">
          <textarea id={`${id}-note`} rows={3} value={note} maxLength={8000} onChange={(e) => setNote(e.target.value)} className={cn(fieldClasses, "py-2")} />
        </Field>
        <FormError error={approve.error} />
      </div>
    </Dialog>
  );
}

function ResolveDialog({ detail, onClose }: { detail: ActionDetail; onClose: () => void }) {
  const { action } = detail;
  const [resolution, setResolution] = useState<"keep" | "archive">("keep");
  const resolve = usePsmMutation((reason: string) => psmApi.resolve(action.id, { version: action.version, resolution, reason }));
  return (
    <ReasonDialog
      open
      title={`Resolve ${action.actionNumber}`}
      description="The recommendation was rejected. Keep the action open as a voluntary improvement, or archive it. Nothing is deleted."
      confirmLabel="Record resolution"
      pending={resolve.isPending}
      error={resolve.error}
      onClose={onClose}
      onConfirm={(reason) => resolve.mutate(reason, { onSuccess: () => (toast("success", "Resolution recorded"), onClose()) })}
    >
      <fieldset className="flex flex-col gap-2 text-sm">
        <legend className="mb-1 font-medium">Resolution</legend>
        <label className="flex items-center gap-2">
          <input type="radio" name="psm-resolution" checked={resolution === "keep"} onChange={() => setResolution("keep")} />
          Keep the action
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" name="psm-resolution" checked={resolution === "archive"} onChange={() => setResolution("archive")} />
          Archive the action
        </label>
      </fieldset>
    </ReasonDialog>
  );
}

const UPDATE_LABELS: Record<string, string> = {
  comment: "Comment",
  status_change: "Status changed",
  assignment: "Assignment",
  closure_request: "Closure requested",
  closure_approved: "Closure verified",
  closure_returned: "Closure returned",
  reopened: "Reopened",
  disposition: "Disposition",
};

function UpdatesSection({ detail }: { detail: ActionDetail }) {
  const id = useId();
  const { action, abilities: a } = detail;
  const [body, setBody] = useState("");
  const comment = usePsmMutation((text: string) => psmApi.comment(action.id, { body: text }));
  return (
    <TableSection id={`${id}-updates`} title="Updates" description="Comments and recorded changes, newest first.">
      {(a.manageActions || a.requestClosure) && (
        <div className="space-y-2 border-b p-4">
          <Field id={`${id}-comment`} label="Add a comment">
            <textarea id={`${id}-comment`} rows={2} value={body} maxLength={8000} onChange={(e) => setBody(e.target.value)} className={cn(fieldClasses, "py-2")} />
          </Field>
          <div className="flex justify-end">
            <Button
              size="sm"
              disabled={!body.trim() || comment.isPending}
              onClick={() => comment.mutate(body.trim(), { onSuccess: () => setBody("") })}
            >
              {comment.isPending ? "Posting…" : "Post comment"}
            </Button>
          </div>
          <FormError error={comment.error} />
        </div>
      )}
      {detail.updates.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No updates yet.</p>
      ) : (
        <ol className="divide-y">
          {[...detail.updates].reverse().map((u) => (
            <li key={u.id} className="px-4 py-2 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{UPDATE_LABELS[u.updateType] ?? u.updateType}</span>
                {u.newStatus && (
                  <span className="text-xs text-muted-foreground">
                    {u.previousStatus ? `${ACTION_STATUS_LABELS[u.previousStatus] ?? u.previousStatus} → ` : ""}
                    {ACTION_STATUS_LABELS[u.newStatus] ?? u.newStatus}
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  {u.createdByName} · {formatTimestamp(u.createdAt)}
                </span>
              </p>
              <p className="mt-0.5 whitespace-pre-wrap">{u.body}</p>
            </li>
          ))}
        </ol>
      )}
    </TableSection>
  );
}

const NOTIFICATION_TONES: Record<string, StatusTone> = { queued: "pending", sent: "success", failed: "danger", skipped: "neutral" };

function NotificationsSection({ notifications, mailEnabled }: { notifications: Notification[]; mailEnabled: boolean }) {
  const id = useId();
  return (
    <TableSection
      id={`${id}-notifications`}
      title="Email notifications"
      description={
        mailEnabled
          ? "Sent marks a message the mail server accepted. Delivery problems never undo the change that caused them."
          : "Email is not configured; not sent. Changes are recorded here and can be delivered once email is set up."
      }
    >
      {notifications.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No notifications for this action.</p>
      ) : (
        <ul className="divide-y">
          {notifications.map((n) => (
            <li key={n.id} className="flex flex-wrap items-start justify-between gap-2 px-4 py-2 text-sm">
              <div className="min-w-0">
                <p className="font-medium">{n.subject}</p>
                <p className="text-xs text-muted-foreground">
                  To {n.recipientName ?? "no recipient"}
                  {n.recipientEmail ? ` <${n.recipientEmail}>` : ""} · queued {formatTimestamp(n.createdAt)}
                  {n.sentAt ? ` · sent ${formatTimestamp(n.sentAt)}` : ""}
                  {n.status !== "sent" && n.lastAttemptAt ? ` · last attempt ${formatTimestamp(n.lastAttemptAt)}` : ""}
                </p>
                {n.statusDetail && <p className="text-xs text-muted-foreground">{n.statusDetail}</p>}
              </div>
              <StatusBadge tone={NOTIFICATION_TONES[n.status] ?? "neutral"}>
                {n.status === "queued" && !mailEnabled ? "Not sent (email not configured)" : (NOTIFICATION_STATUS_LABELS[n.status] ?? n.status)}
              </StatusBadge>
            </li>
          ))}
        </ul>
      )}
    </TableSection>
  );
}
