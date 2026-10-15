"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { toast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, fieldClasses, inputClasses } from "@/features/quality/cost/record-form";
import { cn } from "@/lib/utils";

import { psmApi, studyHref, type PsmOptions, type Study, type StudyFields } from "./api";
import { FormError } from "./psm-shared";
import { usePsmMutation } from "./use-psm";

const STATUSES = [
  { value: "active", label: "Active" },
  { value: "complete", label: "Complete" },
  { value: "archived", label: "Archived" },
];

/** Creates a study (study null) or edits one. The recommendation prefix is fixed once recommendations exist. */
export function StudyDialog({ options, study, onClose }: { options: PsmOptions; study: Study | null; onClose: () => void }) {
  const id = useId();
  const router = useRouter();
  const [draft, setDraft] = useState({
    studyCode: study?.studyCode ?? "",
    title: study?.title ?? "",
    year: String(study?.year ?? new Date().getFullYear()),
    studyTypeId: String(study?.studyTypeId ?? options.studyTypes[0]?.id ?? ""),
    description: study?.description ?? "",
    recommendationPrefix: study?.recommendationPrefix ?? "",
    status: study?.status ?? "active",
    studyDate: study?.studyDate ?? "",
    areaIds: study?.areas.map((a) => a.id) ?? [],
  });
  const save = usePsmMutation((body: StudyFields) => (study ? psmApi.updateStudy(study.id, body) : psmApi.createStudy(body)));
  const set = (patch: Partial<typeof draft>) => setDraft({ ...draft, ...patch });
  const ready = draft.studyCode.trim() && draft.title.trim() && draft.recommendationPrefix.trim() && draft.studyTypeId && draft.year;

  const submit = () =>
    save.mutate(
      {
        studyCode: draft.studyCode.trim(),
        title: draft.title.trim(),
        year: Number(draft.year),
        studyTypeId: Number(draft.studyTypeId),
        description: draft.description.trim() || null,
        recommendationPrefix: draft.recommendationPrefix.trim().toUpperCase(),
        status: draft.status,
        studyDate: draft.studyDate || null,
        areaIds: draft.areaIds,
        version: study?.version,
      },
      {
        onSuccess: (saved) => {
          toast("success", study ? "Study saved" : "Study created", saved.title);
          onClose();
          if (!study) router.push(studyHref(saved.id));
        },
      },
    );

  return (
    <Dialog
      open
      onClose={onClose}
      title={study ? `Edit ${study.title}` : "New PHA study"}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!ready || save.isPending} onClick={submit}>
            {save.isPending ? "Saving…" : study ? "Save study" : "Create study"}
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id={`${id}-code`} label="Study code" required hint="Letters, digits, dot, dash or underscore.">
          <input id={`${id}-code`} value={draft.studyCode} maxLength={60} onChange={(e) => set({ studyCode: e.target.value })} className={inputClasses} />
        </Field>
        <Field id={`${id}-title`} label="Title" required>
          <input id={`${id}-title`} value={draft.title} maxLength={200} onChange={(e) => set({ title: e.target.value })} className={inputClasses} />
        </Field>
        <Field id={`${id}-type`} label="Study type" required>
          <select id={`${id}-type`} value={draft.studyTypeId} onChange={(e) => set({ studyTypeId: e.target.value })} className={inputClasses}>
            {options.studyTypes.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field id={`${id}-year`} label="Year" required>
          <input id={`${id}-year`} type="number" min={1990} max={2100} value={draft.year} onChange={(e) => set({ year: e.target.value })} className={inputClasses} />
        </Field>
        <Field
          id={`${id}-prefix`}
          label="Recommendation ID prefix"
          required
          hint={study && study.counts.recommendations > 0 ? "Fixed: the study has recommendations." : "Recommendation IDs read PREFIX-001, PREFIX-002…"}
        >
          <input
            id={`${id}-prefix`}
            value={draft.recommendationPrefix}
            maxLength={30}
            disabled={Boolean(study && study.counts.recommendations > 0)}
            onChange={(e) => set({ recommendationPrefix: e.target.value.toUpperCase() })}
            className={inputClasses}
          />
        </Field>
        <Field id={`${id}-date`} label="Study date">
          <input id={`${id}-date`} type="date" value={draft.studyDate} onChange={(e) => set({ studyDate: e.target.value })} className={inputClasses} />
        </Field>
        <Field id={`${id}-status`} label="Status" required>
          <select id={`${id}-status`} value={draft.status} onChange={(e) => set({ status: e.target.value })} className={inputClasses}>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <fieldset className="flex flex-col gap-1">
          <legend className="text-sm font-medium">
            Areas <span className="font-normal text-muted-foreground">(optional)</span>
          </legend>
          <div className="flex max-h-32 flex-col gap-1 overflow-y-auto rounded-md border p-2">
            {options.areas.map((area) => (
              <label key={area.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.areaIds.includes(area.id)}
                  onChange={(e) =>
                    set({ areaIds: e.target.checked ? [...draft.areaIds, area.id] : draft.areaIds.filter((a) => a !== area.id) })
                  }
                />
                {area.name}
              </label>
            ))}
          </div>
        </fieldset>
        <Field id={`${id}-description`} label="Description" className="sm:col-span-2">
          <textarea
            id={`${id}-description`}
            rows={3}
            value={draft.description}
            maxLength={8000}
            onChange={(e) => set({ description: e.target.value })}
            className={cn(fieldClasses, "py-2")}
          />
        </Field>
        <div className="sm:col-span-2">
          <FormError error={save.error} />
        </div>
      </div>
    </Dialog>
  );
}
