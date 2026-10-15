"use client";

import { Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { Field, fieldClasses, inputClasses } from "@/features/quality/cost/record-form";
import { cn } from "@/lib/utils";

import { psmApi, recommendationHref, type PsmOptions } from "./api";
import { BackToPha } from "./recommendation-page";
import { EYEBROW, FormError, PsmError } from "./psm-shared";
import { EMPTY_SCENARIO, NodeSelect, ScenarioFieldsForm, scenarioBody, scenarioComplete, type ScenarioDraft } from "./scenario-fields";
import { usePsmMutation, usePsmOptions } from "./use-psm";

export function NewRecommendationPage({ initialStudyId }: { initialStudyId: string }) {
  const options = usePsmOptions();
  if (options.isError) {
    return (
      <div className="space-y-5">
        <BackToPha />
        <PsmError error={options.error} onRetry={() => void options.refetch()} />
      </div>
    );
  }
  if (!options.data) return <p className="py-6 text-sm text-muted-foreground">Loading…</p>;
  return <RecommendationForm options={options.data} initialStudyId={initialStudyId} />;
}

function RecommendationForm({ options, initialStudyId }: { options: PsmOptions; initialStudyId: string }) {
  const id = useId();
  const router = useRouter();
  const studies = options.studies.filter((s) => s.active || String(s.id) === initialStudyId);
  const [studyId, setStudyId] = useState(studies.some((s) => String(s.id) === initialStudyId) ? initialStudyId : "");
  const [areaEquipment, setAreaEquipment] = useState("");
  const [text, setText] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [notes, setNotes] = useState("");
  const [scenarios, setScenarios] = useState<ScenarioDraft[]>([EMPTY_SCENARIO]);
  const create = usePsmMutation((isDraft: boolean) =>
    psmApi.createRecommendation({
      studyId: Number(studyId),
      areaEquipment: areaEquipment.trim(),
      recommendationText: text.trim(),
      processNodeId: nodeId ? Number(nodeId) : null,
      notes: notes.trim() || null,
      isDraft,
      scenarios: scenarios.filter(scenarioComplete).map(scenarioBody),
    }),
  );

  if (!options.abilities.editRecommendation) {
    return (
      <div className="space-y-5">
        <BackToPha />
        <p className="text-sm text-muted-foreground">You do not have permission to add recommendations.</p>
      </div>
    );
  }

  const basics = Boolean(studyId && areaEquipment.trim() && text.trim());
  const complete = scenarios.filter(scenarioComplete).length;
  const partial = scenarios.some((s) => !scenarioComplete(s) && (s.event || s.cause || s.consequence || s.risk));
  const submit = (isDraft: boolean) =>
    create.mutate(isDraft, {
      onSuccess: (saved) => {
        toast("success", `${saved.displayId} added`, isDraft ? "Saved as a draft." : undefined);
        router.push(recommendationHref(saved.id));
      },
    });

  return (
    <div className="space-y-5">
      <BackToPha />
      <PageHeader eyebrow={EYEBROW} title="New recommendation" description="The next recommendation number in the study is assigned when it is saved. It starts in Pending Review." />
      <section className="grid grid-cols-1 gap-4 rounded-lg border bg-card p-4 sm:grid-cols-2 sm:p-5">
        <Field id={`${id}-study`} label="PHA study" required>
          <select id={`${id}-study`} value={studyId} onChange={(e) => setStudyId(e.target.value)} className={inputClasses}>
            <option value="">Choose a study</option>
            {studies.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field id={`${id}-equipment`} label="Area / equipment" required>
          <input id={`${id}-equipment`} value={areaEquipment} maxLength={200} onChange={(e) => setAreaEquipment(e.target.value)} className={inputClasses} />
        </Field>
        <Field id={`${id}-text`} label="Recommendation" required className="sm:col-span-2">
          <textarea id={`${id}-text`} rows={4} value={text} maxLength={8000} onChange={(e) => setText(e.target.value)} className={cn(fieldClasses, "py-2")} />
        </Field>
        <Field id={`${id}-node`} label="Process node">
          <NodeSelect id={`${id}-node`} value={nodeId} nodes={options.processNodes} canAdd onChange={setNodeId} />
        </Field>
        <Field id={`${id}-notes`} label="Notes" className="sm:col-span-2">
          <textarea id={`${id}-notes`} rows={2} value={notes} maxLength={8000} onChange={(e) => setNotes(e.target.value)} className={cn(fieldClasses, "py-2")} />
        </Field>
      </section>

      <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-5">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Hazard scenarios</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              At least one scenario with event, cause, consequence and risk. The governing risk is the highest of them.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => setScenarios([...scenarios, EMPTY_SCENARIO])}>
            <Plus />
            Add scenario
          </Button>
        </header>
        {scenarios.map((draft, index) => (
          <fieldset key={index} className="space-y-3 rounded-md border p-3">
            <legend className="flex items-center gap-2 px-1 text-sm font-medium">
              Scenario {index + 1}
              {scenarios.length > 1 && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove scenario ${index + 1}`}
                  onClick={() => setScenarios(scenarios.filter((_, i) => i !== index))}
                >
                  <Trash2 />
                </Button>
              )}
            </legend>
            <ScenarioFieldsForm
              draft={draft}
              nodes={options.processNodes}
              canAddNode
              onChange={(next) => setScenarios(scenarios.map((s, i) => (i === index ? next : s)))}
            />
          </fieldset>
        ))}
      </section>

      {partial && <p className="text-sm text-warning">Incomplete scenarios are not saved. Complete them or remove them.</p>}
      <FormError error={create.error} />
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" disabled={!basics || partial || create.isPending} onClick={() => submit(true)}>
          Save as draft
        </Button>
        <Button disabled={!basics || partial || complete === 0 || create.isPending} onClick={() => submit(false)}>
          {create.isPending ? "Saving…" : "Save recommendation"}
        </Button>
      </div>
    </div>
  );
}
