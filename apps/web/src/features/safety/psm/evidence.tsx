"use client";

import { Paperclip, Upload } from "lucide-react";
import { useId, useRef, useState } from "react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { TableSection } from "@/features/quality/cost/cost-shared";
import { formatTimestamp } from "@/features/quality/cost/format";
import { Field, inputClasses } from "@/features/quality/cost/record-form";

import { attachmentHref, MAX_FILE_BYTES, psmApi, uploadEvidence, type Attachment, type CodeLabel } from "./api";
import { FormError, ReasonDialog } from "./psm-shared";
import { usePsmMutation } from "./use-psm";

function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Evidence files. Removal needs a reason and keeps the record (shown as
 * removed); while closure is being verified or after closing, evidence is locked.
 */
export function EvidenceSection({
  target,
  attachments,
  evidenceTypes,
  canUpload,
  canRemove,
  lockedReason,
}: {
  target: { recommendationId: number } | { actionId: number };
  attachments: Attachment[];
  evidenceTypes: CodeLabel[];
  canUpload: boolean;
  canRemove: boolean;
  lockedReason?: string;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [evidenceType, setEvidenceType] = useState(evidenceTypes[0]?.code ?? "other");
  const [description, setDescription] = useState("");
  const [removing, setRemoving] = useState<Attachment | null>(null);
  const upload = usePsmMutation((f: File) => uploadEvidence(target, f, evidenceType, description.trim() || null));
  const remove = usePsmMutation(({ attachmentId, reason }: { attachmentId: number; reason: string }) =>
    psmApi.removeAttachment(attachmentId, reason),
  );
  const labels = Object.fromEntries(evidenceTypes.map((t) => [t.code, t.label]));
  const tooLarge = file !== null && file.size > MAX_FILE_BYTES;
  const active = attachments.filter((a) => !a.removedAt);
  const removed = attachments.filter((a) => a.removedAt);

  return (
    <TableSection
      id={`${id}-evidence`}
      title="Evidence"
      description={lockedReason ?? `${active.length} ${active.length === 1 ? "file" : "files"}. PDF, images, Office documents and text, up to 10 MB each.`}
    >
      {attachments.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No evidence attached.</p>
      ) : (
        <ul className="divide-y">
          {[...active, ...removed].map((a) => (
            <li key={a.id} className="flex flex-wrap items-start justify-between gap-2 px-4 py-2 text-sm">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2">
                  <Paperclip aria-hidden className="size-4 text-muted-foreground" />
                  {a.removedAt ? (
                    <span className="text-muted-foreground line-through">{a.originalFileName}</span>
                  ) : (
                    <a href={attachmentHref(a.id)} className="font-medium text-primary hover:underline" download>
                      {a.originalFileName}
                    </a>
                  )}
                  <StatusBadge tone="neutral">{labels[a.evidenceType] ?? a.evidenceType}</StatusBadge>
                  {a.removedAt && <StatusBadge tone="neutral">Removed</StatusBadge>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {size(a.sizeBytes)} · {a.uploadedByName} · {formatTimestamp(a.uploadedAt)}
                  {a.description ? ` · ${a.description}` : ""}
                </p>
                {a.removedAt && (
                  <p className="text-xs text-muted-foreground">
                    Removed by {a.removedByName} · {formatTimestamp(a.removedAt)} · {a.removalReason}
                  </p>
                )}
              </div>
              {canRemove && !a.removedAt && !lockedReason && (
                <Button variant="ghost" size="sm" onClick={() => setRemoving(a)}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canUpload && !lockedReason && (
        <div className="grid grid-cols-1 gap-3 border-t p-4 sm:grid-cols-[1fr_12rem_1fr_auto] sm:items-end">
          <Field id={`${id}-file`} label="File" required>
            <input
              ref={input}
              id={`${id}-file`}
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm file:mr-3 file:rounded-md file:border file:bg-card file:px-3 file:py-1.5 file:text-sm"
            />
          </Field>
          <Field id={`${id}-type`} label="Evidence type" required>
            <select id={`${id}-type`} value={evidenceType} onChange={(e) => setEvidenceType(e.target.value)} className={inputClasses}>
              {evidenceTypes.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <Field id={`${id}-description`} label="Description">
            <input id={`${id}-description`} value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)} className={inputClasses} />
          </Field>
          <Button
            disabled={!file || tooLarge || upload.isPending}
            onClick={() =>
              file &&
              upload.mutate(file, {
                onSuccess: () => {
                  toast("success", "Evidence attached", file.name);
                  setFile(null);
                  setDescription("");
                  if (input.current) input.current.value = "";
                },
              })
            }
          >
            <Upload />
            {upload.isPending ? "Uploading…" : "Attach"}
          </Button>
          <div className="sm:col-span-4">
            {tooLarge && <p className="text-sm text-destructive">This file is larger than 10 MB.</p>}
            <FormError error={upload.error} />
          </div>
        </div>
      )}
      {removing && (
        <ReasonDialog
          open
          title={`Remove ${removing.originalFileName}`}
          description="The file is kept on record and shown as removed, with your reason."
          confirmLabel="Remove evidence"
          pending={remove.isPending}
          error={remove.error}
          onClose={() => setRemoving(null)}
          onConfirm={(reason) =>
            remove.mutate({ attachmentId: removing.id, reason }, { onSuccess: () => setRemoving(null) })
          }
        />
      )}
    </TableSection>
  );
}
