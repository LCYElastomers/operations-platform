"use client";

import { Plus } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, fieldClasses, inputClasses } from "@/features/quality/cost/record-form";
import { cn } from "@/lib/utils";

import { psmApi, RISK_LABELS, RISKS, type Option, type Risk, type Scenario, type ScenarioFields } from "./api";
import { FormError } from "./psm-shared";
import { usePsmMutation } from "./use-psm";

export type ScenarioDraft = {
  event: string;
  cause: string;
  consequence: string;
  risk: Risk | "";
  areaEquipment: string;
  processNodeId: string;
};

export const EMPTY_SCENARIO: ScenarioDraft = { event: "", cause: "", consequence: "", risk: "", areaEquipment: "", processNodeId: "" };

export function scenarioDraftOf(s: Scenario): ScenarioDraft {
  return {
    event: s.event,
    cause: s.cause,
    consequence: s.consequence,
    risk: s.risk,
    areaEquipment: s.areaEquipment ?? "",
    processNodeId: s.processNodeId ? String(s.processNodeId) : "",
  };
}

export function scenarioComplete(d: ScenarioDraft) {
  return Boolean(d.event.trim() && d.cause.trim() && d.consequence.trim() && d.risk);
}

export function scenarioBody(d: ScenarioDraft): ScenarioFields {
  return {
    event: d.event.trim(),
    cause: d.cause.trim(),
    consequence: d.consequence.trim(),
    risk: d.risk as Risk,
    areaEquipment: d.areaEquipment.trim() || null,
    processNodeId: d.processNodeId ? Number(d.processNodeId) : null,
  };
}

/** A process node select, with adding a node for those allowed to. */
export function NodeSelect({
  id,
  value,
  nodes,
  canAdd,
  onChange,
}: {
  id: string;
  value: string;
  nodes: Option[];
  canAdd: boolean;
  onChange: (value: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const add = usePsmMutation((nodeName: string) => psmApi.saveReference("process-nodes", { name: nodeName, active: true }));
  const listed = nodes.filter((n) => n.active || String(n.id) === value);
  return (
    <div className="flex gap-2">
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={inputClasses}>
        <option value="">Not recorded</option>
        {listed.map((n) => (
          <option key={n.id} value={n.id}>
            {n.name}
          </option>
        ))}
      </select>
      {canAdd && (
        <Button variant="outline" size="sm" className="h-9 pointer-coarse:h-11" onClick={() => setAdding(true)} aria-label="Add a process node">
          <Plus />
        </Button>
      )}
      {adding && (
        <Dialog
          open
          onClose={() => setAdding(false)}
          title="Add a process node"
          description="Nodes are shared by every study. A name that matches an existing node is refused."
          footer={
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setAdding(false)}>
                Cancel
              </Button>
              <Button
                disabled={!name.trim() || add.isPending}
                onClick={() =>
                  add.mutate(name.trim(), {
                    onSuccess: (node) => {
                      onChange(String(node.id));
                      setAdding(false);
                      setName("");
                    },
                  })
                }
              >
                Add node
              </Button>
            </div>
          }
        >
          <div className="space-y-3">
            <Field id={`${id}-new-node`} label="Node name" required>
              <input id={`${id}-new-node`} value={name} maxLength={1000} onChange={(e) => setName(e.target.value)} className={inputClasses} />
            </Field>
            <FormError error={add.error} />
          </div>
        </Dialog>
      )}
    </div>
  );
}

export function ScenarioFieldsForm({
  draft,
  nodes,
  canAddNode,
  onChange,
}: {
  draft: ScenarioDraft;
  nodes: Option[];
  canAddNode: boolean;
  onChange: (draft: ScenarioDraft) => void;
}) {
  const id = useId();
  const set = (patch: Partial<ScenarioDraft>) => onChange({ ...draft, ...patch });
  const area = (name: "event" | "cause" | "consequence", label: string) => (
    <Field id={`${id}-${name}`} label={label} required className="sm:col-span-2">
      <textarea
        id={`${id}-${name}`}
        rows={2}
        value={draft[name]}
        maxLength={8000}
        onChange={(e) => set({ [name]: e.target.value })}
        className={cn(fieldClasses, "py-2")}
      />
    </Field>
  );
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {area("event", "Event")}
      {area("cause", "Cause")}
      {area("consequence", "Consequence")}
      <Field id={`${id}-risk`} label="Risk" required>
        <select id={`${id}-risk`} value={draft.risk} onChange={(e) => set({ risk: e.target.value as Risk })} className={inputClasses}>
          <option value="">Choose a risk rating</option>
          {RISKS.map((risk) => (
            <option key={risk} value={risk}>
              {RISK_LABELS[risk]}
            </option>
          ))}
        </select>
      </Field>
      <Field id={`${id}-equipment`} label="Area / equipment" hint="When it differs from the recommendation's.">
        <input id={`${id}-equipment`} value={draft.areaEquipment} maxLength={200} onChange={(e) => set({ areaEquipment: e.target.value })} className={inputClasses} />
      </Field>
      <Field id={`${id}-node`} label="Process node" className="sm:col-span-2">
        <NodeSelect id={`${id}-node`} value={draft.processNodeId} nodes={nodes} canAdd={canAddNode} onChange={(processNodeId) => set({ processNodeId })} />
      </Field>
    </div>
  );
}
