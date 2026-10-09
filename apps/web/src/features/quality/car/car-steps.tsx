"use client";

import { Plus, Trash2 } from "lucide-react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { NotEntered } from "../cost/cost-shared";
import { formatDate, formatTimestamp, usd } from "../cost/format";
import { Field, fieldClasses, inputClasses } from "../cost/record-form";
import { historyChanges } from "../cost/record-dialog";

import { ActionsPanel } from "./actions-panel";
import { canWithdrawApproval, carSaveError, describeCarError, type Car, type CarAbilities, type CarOptions } from "./api";
import { COST_LINES, costTotal, EMPTY_WHY, type WhyDraft } from "./car-draft";
import {
  FieldGrid,
  PersonInput,
  SelectInput,
  StepSection,
  SubHeading,
  TextArea,
  TextInput,
  useDraft,
  YesNoInput,
} from "./car-fields";
import {
  ActionProgressLabel,
  CarStatusBadge,
  choiceOptions,
  DueBadge,
  EffectivenessBadge,
} from "./car-shared";
import { QualityCostPanel } from "./quality-cost-panel";
import { useCarHistory, useRecordApproval, useWithdrawApproval } from "./use-car";

export type StepProps = {
  car: Car | null;
  options: CarOptions;
  canEdit: boolean;
  canEditCost: boolean;
  dirty: boolean;
  abilities: CarAbilities;
  /** The signed-in user; null before the CAR is saved. */
  currentUserId: string | null;
};

export function IdentifyStep({ options, abilities }: StepProps) {
  const { draft } = useDraft();
  return (
    <StepSection title="1 · Identify the nonconformity" description="What happened, where it came from and who owns the CAR.">
      <FieldGrid>
        <TextInput name="subject" label="Subject / issue" required className="sm:col-span-2" />
        <TextInput name="requestDate" label="Request date" type="date" required />
        <PersonInput name="requestedBy" label="Requested by" />
        <PersonInput
          name="assignedTo"
          label="Assigned to"
          hint={abilities.assign ? undefined : "Assigning a CAR needs the car.assign permission."}
        />
        <TextInput name="dueDate" label="Due date" type="date" />
        <SelectInput name="sourceCode" label="Source" options={choiceOptions(options.sources, draft.sourceCode)} />
        <SelectInput
          name="departmentCode"
          label="Department"
          options={choiceOptions(options.departments, draft.departmentCode)}
        />
      </FieldGrid>
      <SubHeading>When it occurred</SubHeading>
      <FieldGrid className="xl:grid-cols-4">
        <TextInput name="startedOn" label="Start date" type="date" />
        <TextInput name="startedTime" label="Start time" type="time" />
        <TextInput name="endedOn" label="End date" type="date" />
        <TextInput name="endedTime" label="End time" type="time" />
      </FieldGrid>
      <SubHeading>Description</SubHeading>
      <FieldGrid>
        <YesNoInput name="previousOccurrence" label="Previous occurrence?" />
        <TextInput name="previousCar" label="Previous CAR number" hint="If this repeats an earlier CAR." />
        <TextArea name="nonconformityDescription" label="Nonconformity description" rows={4} className="xl:col-span-3" />
        <TextArea name="objectiveEvidence" label="Objective evidence" className="xl:col-span-3" />
      </FieldGrid>
    </StepSection>
  );
}

export function ContainStep({ options }: StepProps) {
  const { id, draft, update, problems } = useDraft();
  const dispositions = choiceOptions(options.dispositions, draft.dispositionCodes);
  const toggle = (code: string, checked: boolean) =>
    update({
      dispositionCodes: checked
        ? [...draft.dispositionCodes, code]
        : draft.dispositionCodes.filter((value) => value !== code),
    });
  return (
    <StepSection title="2 · Immediate correction and containment" description="What was done straight away to contain the problem.">
      <FieldGrid>
        <TextArea name="immediateActions" label="Immediate actions taken" rows={4} className="xl:col-span-3" />
        <PersonInput name="containmentOwner" label="Containment owner" />
        <TextInput name="containmentCompletedOn" label="Containment completed on" type="date" />
      </FieldGrid>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">
          Disposition <span className="font-normal text-muted-foreground">(optional, choose any)</span>
        </legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {dispositions.map((option) => (
            <label key={option.value} className="flex items-center gap-2 text-sm pointer-coarse:min-h-11">
              <input
                type="checkbox"
                checked={draft.dispositionCodes.includes(option.value)}
                onChange={(event) => toggle(option.value, event.target.checked)}
                className="size-4"
              />
              {option.label}
            </label>
          ))}
        </div>
        {problems.dispositionCodes && <p className="text-xs text-destructive">{problems.dispositionCodes}</p>}
      </fieldset>
      <FieldGrid>
        <TextInput name="dispositionOther" label="Other disposition" />
      </FieldGrid>
      <SubHeading>Risk</SubHeading>
      <FieldGrid>
        <YesNoInput name="safetyHazard" label="Safety hazard?" />
        <YesNoInput name="environmentalHazard" label="Environmental hazard?" />
        <YesNoInput name="customerImpact" label="Customer impact?" />
      </FieldGrid>
      <p id={`${id}-yes-no`} className="text-xs text-muted-foreground">
        &ldquo;Not recorded&rdquo; is kept apart from &ldquo;No&rdquo;.
      </p>
    </StepSection>
  );
}

export function InvestigateStep({ options }: StepProps) {
  const { draft } = useDraft();
  return (
    <StepSection title="3 · Investigation and root cause" description="How it happened, the root cause, and the Why-Why analysis.">
      <FieldGrid>
        <TextInput name="incidentType" label="Incident type" />
        <SelectInput
          name="rootCauseCode"
          label="Root cause category"
          options={choiceOptions(options.rootCauses, draft.rootCauseCode)}
        />
        <TextInput name="equipmentInvolved" label="Equipment involved" />
        <TextInput name="workOrderNumber" label="Work order number" />
        <TextArea name="investigationSummary" label="Investigation summary" rows={4} className="xl:col-span-3" />
        <TextArea name="trueRootCause" label="True root cause" rows={3} className="xl:col-span-3" />
      </FieldGrid>
      <SubHeading>Why-Why analysis</SubHeading>
      <FieldGrid>
        <TextInput name="complaintNumber" label="Complaint number" />
        <TextInput name="dateReported" label="Date reported" type="date" />
        <TextInput name="drNumber" label="DR number" />
        <TextInput name="materialName" label="Material name" />
        <TextInput name="poNumber" label="PO number" />
        <TextInput name="supplier" label="Supplier" />
        <TextInput name="dateDelivered" label="Date delivered" type="date" />
        <TextInput name="productionLot" label="Production lot" />
        <TextInput name="quantityAffected" label="Quantity affected" />
      </FieldGrid>
      <WhyStepsEditor />
    </StepSection>
  );
}

const WHY_COLUMNS: { key: keyof WhyDraft; label: string; type?: "date"; long?: boolean }[] = [
  { key: "what", label: "What", long: true },
  { key: "why", label: "Why", long: true },
  { key: "rootCause", label: "Root cause", long: true },
  { key: "countermeasure", label: "Countermeasure", long: true },
  { key: "who", label: "Who" },
  { key: "targetDate", label: "Target date", type: "date" },
];

function WhyStepsEditor() {
  const { id, draft, update, readOnly } = useDraft();
  const rows = draft.whySteps;
  const setRow = (index: number, patch: Partial<WhyDraft>) =>
    update({ whySteps: rows.map((row, i) => (i === index ? { ...row, ...patch } : row)) });
  return (
    <div className="space-y-2">
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No Why-Why rows recorded.</p>
      ) : (
        <ol className="space-y-3">
          {rows.map((row, index) => (
            <li key={index} className="rounded-md border p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium">Why {index + 1}</span>
                {!readOnly && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => update({ whySteps: rows.filter((_, i) => i !== index) })}
                    aria-label={`Remove why ${index + 1}`}
                  >
                    <Trash2 />
                  </Button>
                )}
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {WHY_COLUMNS.map((column) => {
                  const fieldId = `${id}-why-${index}-${column.key}`;
                  return (
                    <Field key={column.key} id={fieldId} label={column.label}>
                      {column.long ? (
                        <textarea
                          id={fieldId}
                          rows={2}
                          maxLength={8000}
                          value={row[column.key]}
                          onChange={(event) => setRow(index, { [column.key]: event.target.value })}
                          className={cn(fieldClasses, "py-2")}
                        />
                      ) : (
                        <input
                          id={fieldId}
                          type={column.type ?? "text"}
                          maxLength={column.type ? undefined : 200}
                          value={row[column.key]}
                          onChange={(event) => setRow(index, { [column.key]: event.target.value })}
                          className={inputClasses}
                        />
                      )}
                    </Field>
                  );
                })}
              </div>
            </li>
          ))}
        </ol>
      )}
      {!readOnly && rows.length < 20 && (
        <Button variant="outline" size="sm" onClick={() => update({ whySteps: [...rows, { ...EMPTY_WHY }] })}>
          <Plus />
          Add why
        </Button>
      )}
    </div>
  );
}

export function EvaluateStep() {
  return (
    <StepSection title="4 · Systemic evaluation" description="Could the same problem exist elsewhere?">
      <FieldGrid>
        <TextArea name="similarNonconformities" label="Similar nonconformities / where else it could occur" rows={4} className="xl:col-span-3" />
        <YesNoInput name="similarIssueFound" label="Similar issue found?" />
        <YesNoInput name="additionalActionRequired" label="Additional action required?" />
      </FieldGrid>
    </StepSection>
  );
}

export function CorrectStep({ car, options, abilities, currentUserId }: StepProps) {
  return (
    <StepSection
      title="5 · Corrective actions"
      description="Each action is tracked on its own. The CAR cannot be closed until every action is complete."
    >
      <ActionsPanel car={car} options={options} abilities={abilities} currentUserId={currentUserId} />
      <ReportFields>
        <SubHeading>Corrective action plan</SubHeading>
        <FieldGrid>
          <TextArea name="proceduresRevised" label="Procedures revised" className="xl:col-span-3" />
          <YesNoInput name="trainingCompleted" label="Training completed?" />
          <TextInput name="planCompletedOn" label="Actual completion date" type="date" />
          <TextArea name="supportingDocuments" label="Supporting documents" className="xl:col-span-3" />
        </FieldGrid>
      </ReportFields>
    </StepSection>
  );
}

/** Report fields inside a step whose other controls follow their own permissions. */
function ReportFields({ children }: { children: React.ReactNode }) {
  const { readOnly } = useDraft();
  return (
    <fieldset disabled={readOnly} className="min-w-0 space-y-4">
      {children}
    </fieldset>
  );
}

export function VerifyStep({ car, options, abilities }: StepProps) {
  return (
    <StepSection
      title="6 · Verify effectiveness"
      description="Did the actions work? Recorded separately from completing the actions."
      actions={car ? <EffectivenessBadge car={car} /> : undefined}
    >
      {!abilities.reviewEffectiveness && (
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Recording the effectiveness review needs the car.reviewEffectiveness permission.
        </p>
      )}
      <FieldGrid>
        <TextArea name="successCriteria" label="Success criteria" className="xl:col-span-3" />
        <TextArea name="effectivenessEvidence" label="Evidence of effectiveness" rows={4} className="xl:col-span-3" />
        <RecordedBy
          label="Reviewer"
          name={car?.reviewer ?? null}
          linked={car?.reviewerUserId != null}
          empty="Recorded as you when you save the review"
        />
        <TextInput name="reviewDate" label="Review date" type="date" />
        <SelectInput
          name="effectivenessResult"
          label="Result"
          placeholder="Not reviewed"
          options={options.effectivenessResults.map((r) => ({ value: r.code, label: r.label }))}
        />
        <TextInput
          name="followUpReference"
          label="Follow-up CAR or action"
          hint="Required to close a CAR found Not Effective."
        />
      </FieldGrid>
    </StepSection>
  );
}

export function CostStep({ car, abilities, dirty }: StepProps) {
  const { draft } = useDraft();
  const total = costTotal(draft);
  const entered = COST_LINES.some(({ field }) => draft[field].trim());
  return (
    <StepSection title="7 · Cost impact" description="Leave a line blank when its cost is not known. Blank is not $0.">
      <FieldGrid>
        {COST_LINES.map(({ field, label }) => (
          <TextInput key={field} name={field} label={`${label} ($)`} />
        ))}
      </FieldGrid>
      <p className="text-sm" aria-live="polite">
        <span className="text-muted-foreground">Total cost impact: </span>
        <span className="font-semibold tabular-nums">
          {total !== null ? usd(String(total), 2) : entered ? "Check the amounts entered" : "Not entered"}
        </span>
      </p>
      <QualityCostPanel
        car={car}
        canEdit={abilities.linkQualityCost}
        canEditCost={abilities.createQualityCost}
        dirty={dirty}
      />
    </StepSection>
  );
}

export function CloseStep({ car, options, abilities, currentUserId, dirty }: StepProps) {
  const { draft } = useDraft();
  const statusOptions = options.carStatuses.map((s) => ({ value: s.code, label: s.label }));
  const closing = draft.status === "closed" && car?.status !== "closed";
  const reopening = car?.status === "closed" && draft.status !== "closed";
  const checks = car
    ? [
        { ok: car.actions.total > 0 && car.actions.outstanding === 0, label: car.actions.total === 0 ? "No corrective actions recorded" : `${car.actions.complete} of ${car.actions.total} actions complete` },
        { ok: draft.effectivenessResult !== "", label: "Effectiveness review result recorded" },
      ]
    : [];
  return (
    <StepSection
      title="8 · Approval and closure"
      description="Approvals are recorded under the name of the signed-in user who records them, dated that day. They are not digital signatures."
    >
      {car ? (
        <ApprovalsPanel car={car} options={options} abilities={abilities} currentUserId={currentUserId} dirty={dirty} />
      ) : (
        <p className="text-sm text-muted-foreground">Approvals can be recorded once the CAR is saved.</p>
      )}
      <ReportFields>
        <SubHeading>Closure</SubHeading>
        {checks.length > 0 && (
          <ul className="space-y-1 text-sm" aria-label="Ready to close">
            {checks.map((check) => (
              <li key={check.label} className="flex items-center gap-2">
                <StatusBadge tone={check.ok ? "success" : "warning"}>{check.ok ? "Done" : "Open"}</StatusBadge>
                {check.label}
              </li>
            ))}
          </ul>
        )}
        <FieldGrid>
          <SelectInput
            name="status"
            label="CAR status"
            required={car?.status !== null}
            placeholder={draft.status === "" ? "Not recorded" : false}
            options={statusOptions}
          />
          <TextInput name="dateClosed" label="Date closed" type="date" />
          <RecordedBy
            label="Closure approved by"
            name={reopening ? null : (car?.closureApprovedBy ?? null)}
            linked={car?.closureApprovedByUserId != null}
            empty="Recorded as you when you close the CAR"
          />
        </FieldGrid>
        {closing && !abilities.close && (
          <p className="text-sm text-destructive">Closing a CAR needs the car.close permission.</p>
        )}
        {reopening && !abilities.reopen && (
          <p className="text-sm text-destructive">Reopening a CAR needs the car.reopen permission.</p>
        )}
      </ReportFields>
    </StepSection>
  );
}

/** A person the API records from the signed-in user; shown, never typed. */
function RecordedBy({ label, name, linked, empty }: { label: string; name: string | null; linked: boolean; empty: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-sm font-medium">{label}</span>
      <p className="flex h-9 items-center rounded-md border border-dashed px-3 text-sm pointer-coarse:h-11">
        {name ? (
          <span className="truncate">
            {name}
            {!linked && <span className="text-muted-foreground"> (recorded before user accounts)</span>}
          </span>
        ) : (
          <span className="truncate text-muted-foreground">{empty}</span>
        )}
      </p>
    </div>
  );
}

function ApprovalsPanel({
  car,
  options,
  abilities,
  currentUserId,
  dirty,
}: {
  car: Car;
  options: CarOptions;
  abilities: CarAbilities;
  currentUserId: string | null;
  dirty: boolean;
}) {
  const record = useRecordApproval();
  const withdraw = useWithdrawApproval();
  const pending = record.isPending || withdraw.isPending;
  const error = record.error ?? withdraw.error;
  const saved = new Map(car.approvals.map((a) => [a.functionCode, a]));
  const closed = car.status === "closed";
  const response = { abilities, currentUserId };
  const blocked = closed ? "Reopen the CAR to change approvals." : dirty ? "Save or discard your changes before recording approvals." : null;

  return (
    <div className="space-y-2">
      {error && <p className="text-sm text-destructive">{carSaveError(error)?.message ?? describeCarError(error)}</p>}
      {blocked && (abilities.approve || abilities.admin) && <p className="text-xs text-muted-foreground">{blocked}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <caption className="sr-only">Approvals</caption>
          <thead className="border-b">
            <tr>
              <th scope="col" className="py-2 pr-3 text-xs font-medium text-muted-foreground">Function</th>
              <th scope="col" className="py-2 pr-3 text-xs font-medium text-muted-foreground">Approved by</th>
              <th scope="col" className="py-2 pr-3 text-xs font-medium text-muted-foreground">Date</th>
              <th scope="col" className="py-2 text-xs font-medium text-muted-foreground">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {options.approvalFunctions.map((fn) => {
              const approval = saved.get(fn.code);
              return (
                <tr key={fn.code} className="border-b border-border/60 align-middle">
                  <th scope="row" className="py-2 pr-3 font-medium">{fn.label}</th>
                  <td className="py-2 pr-3">
                    {approval ? (
                      <>
                        {approval.name}
                        {approval.userId === null && (
                          <span className="block text-xs text-muted-foreground">
                            From the CAR form · recorded by {approval.recordedByName}
                          </span>
                        )}
                      </>
                    ) : (
                      <NotEntered label="Not approved" />
                    )}
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap">
                    {approval?.approvedOn ? formatDate(approval.approvedOn) : approval ? <NotEntered label="Not dated" /> : "—"}
                  </td>
                  <td className="py-2 text-right">
                    {!approval && abilities.approve && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={pending || blocked !== null}
                        onClick={() => record.mutate({ id: car.id, body: { version: car.version, functionCode: fn.code } })}
                      >
                        Approve as {fn.label}
                      </Button>
                    )}
                    {approval && canWithdrawApproval(approval, response) && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={pending || blocked !== null}
                        onClick={() => withdraw.mutate({ id: car.id, body: { version: car.version, functionCode: fn.code } })}
                      >
                        Withdraw
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RelatedStep({ car, options }: StepProps) {
  const { id, draft, update, readOnly, problems } = useDraft();
  const refs = draft.references;
  const setRef = (index: number, patch: Partial<(typeof refs)[number]>) =>
    update({ references: refs.map((r, i) => (i === index ? { ...r, ...patch } : r)) });
  return (
    <div className="space-y-5">
      <StepSection
        title="Evidence and attachments"
        description="File attachments are not stored by the platform yet. Record where evidence is kept (document numbers, file locations, photos) as Evidence or Document references below."
      >
        <ul className="space-y-1 text-sm">
          {(car?.references ?? []).filter((r) => r.type === "evidence" || r.type === "document").length === 0 ? (
            <li className="text-muted-foreground">No evidence or document references recorded.</li>
          ) : (
            car!.references
              .filter((r) => r.type === "evidence" || r.type === "document")
              .map((r) => (
                <li key={`${r.type}-${r.key}`}>
                  <span className="text-muted-foreground">{r.typeLabel}:</span> {r.key}
                  {r.label && <span className="text-muted-foreground"> ({r.label})</span>}
                </li>
              ))
          )}
        </ul>
      </StepSection>
      <StepSection title="Related records" description="CARs, work orders, documents, MOCs, lots and complaints this CAR relates to.">
        {refs.length === 0 && <p className="text-sm text-muted-foreground">No related records.</p>}
        <ul className="space-y-2">
          {refs.map((ref, index) => (
            <li key={index} className="grid grid-cols-1 gap-2 sm:grid-cols-[12rem_1fr_1fr_auto] sm:items-end">
              <Field id={`${id}-ref-${index}-type`} label="Type">
                <select
                  id={`${id}-ref-${index}-type`}
                  value={ref.type}
                  onChange={(event) => setRef(index, { type: event.target.value })}
                  className={inputClasses}
                >
                  {options.referenceTypes.map((t) => (
                    <option key={t.code} value={t.code}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id={`${id}-ref-${index}-key`} label="Number / location" required>
                <input
                  id={`${id}-ref-${index}-key`}
                  maxLength={200}
                  value={ref.key}
                  onChange={(event) => setRef(index, { key: event.target.value })}
                  className={inputClasses}
                />
              </Field>
              <Field id={`${id}-ref-${index}-label`} label="Description">
                <input
                  id={`${id}-ref-${index}-label`}
                  maxLength={200}
                  value={ref.label}
                  onChange={(event) => setRef(index, { label: event.target.value })}
                  className={inputClasses}
                />
              </Field>
              {!readOnly && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => update({ references: refs.filter((_, i) => i !== index) })}
                  aria-label={`Remove related record ${index + 1}`}
                  className="h-9"
                >
                  <Trash2 />
                </Button>
              )}
            </li>
          ))}
        </ul>
        {problems.references && <p className="text-xs text-destructive">{problems.references}</p>}
        {!readOnly && refs.length < 30 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              update({ references: [...refs, { type: options.referenceTypes[0]?.code ?? "document", key: "", label: "" }] })
            }
          >
            <Plus />
            Add related record
          </Button>
        )}
        <SubHeading>Production data</SubHeading>
        <FieldGrid>
          <TextInput name="product" label="Product" />
          <TextInput name="campaign" label="Campaign" />
          <TextInput name="lot" label="Lot" />
          <TextInput name="location" label="Location" />
          <TextInput name="counterparty" label="Customer / supplier" />
        </FieldGrid>
      </StepSection>
      {car && (car.legacyFields.length > 0 || car.migrationNotes) && (
        <StepSection
          title="Imported from the CAR workbook"
          description="Values from the original form kept as recorded. They are read-only and are not used in figures."
        >
          {car.legacyFields.length > 0 && (
            <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-[minmax(10rem,max-content)_1fr]">
              {car.legacyFields.map((field, index) => (
                <div key={index} className="contents">
                  <dt className="text-muted-foreground">{field.label}</dt>
                  <dd className="whitespace-pre-line">{field.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {car.migrationNotes && (
            <div>
              <h3 className="text-sm font-semibold">Migration notes</h3>
              <p className="mt-1 text-sm whitespace-pre-line text-muted-foreground">{car.migrationNotes}</p>
            </div>
          )}
        </StepSection>
      )}
    </div>
  );
}

export function OverviewSection({ car, onOpenStep }: { car: Car; onOpenStep: (code: string) => void }) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Fact label="Status">
          <span className="flex flex-wrap gap-1">
            <CarStatusBadge car={car} />
            <DueBadge car={car} />
          </span>
        </Fact>
        <Fact label="Due date">{car.dueDate ? formatDate(car.dueDate) : <NotEntered label="Not set" />}</Fact>
        <Fact label="Days open">
          <span className="tabular-nums">{car.daysOpen}</span>
        </Fact>
        <Fact label="Actions">
          <ActionProgressLabel car={car} />
        </Fact>
        <Fact label="Effectiveness">
          <EffectivenessBadge car={car} />
        </Fact>
        <Fact label="Cost impact">
          {car.totalCost === null ? <NotEntered /> : <span className="tabular-nums">{usd(car.totalCost, 2)}</span>}
        </Fact>
        <Fact label="Department">{car.departmentLabel ?? <NotEntered label="Not recorded" />}</Fact>
        <Fact label="Source">{car.sourceLabel ?? <NotEntered label="Not recorded" />}</Fact>
      </div>
      <StepSection title="Progress" description="Select a step to open it.">
        <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {car.steps.map((step, index) => (
            <li key={step.code}>
              <button
                type="button"
                onClick={() => onOpenStep(step.code)}
                className="flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                <span>
                  <span className="mr-1.5 text-muted-foreground tabular-nums">{index + 1}</span>
                  {step.label}
                </span>
                <StepStateBadge state={step.state} />
              </button>
            </li>
          ))}
        </ol>
      </StepSection>
      <StepSection title="Nonconformity">
        <dl className="grid grid-cols-1 gap-x-4 gap-y-3 text-sm sm:grid-cols-[minmax(10rem,max-content)_1fr]">
          <Detail label="Requested">
            {formatDate(car.requestDate)}
            {car.requestedBy && ` by ${car.requestedBy}`}
            {car.requestedBy && !car.requestedByUserId && (
              <span className="text-muted-foreground"> (recorded before user accounts)</span>
            )}
          </Detail>
          <Detail label="Assigned to">{car.assignedTo ?? <NotEntered label="Not assigned" />}</Detail>
          <Detail label="Description">{car.nonconformityDescription ?? <NotEntered />}</Detail>
          <Detail label="Root cause">
            {car.rootCauseLabel ?? <NotEntered label="Not recorded" />}
            {car.trueRootCause && <span className="mt-1 block whitespace-pre-line">{car.trueRootCause}</span>}
          </Detail>
          {car.previousOccurrence && (
            <Detail label="Repeat">
              Previous occurrence{car.previousCar ? `: ${car.previousCar}` : ""}
            </Detail>
          )}
          {car.qualityCost && (
            <Detail label="Quality Cost record">
              {car.qualityCost.recordNumber} · {car.qualityCost.title}
            </Detail>
          )}
          <Detail label="Record">
            {car.source === "legacy_import" ? "Imported from the CAR workbook" : "Entered in the platform"} · created{" "}
            {formatTimestamp(car.createdAt)} by {car.createdByName} · last updated {formatTimestamp(car.updatedAt)} by{" "}
            {car.updatedByName}
          </Detail>
        </dl>
      </StepSection>
    </div>
  );
}

export function StepStateBadge({ state }: { state: "not_started" | "in_progress" | "complete" }) {
  if (state === "complete") return <StatusBadge tone="success">Complete</StatusBadge>;
  if (state === "in_progress") return <StatusBadge tone="info">In progress</StatusBadge>;
  return <StatusBadge tone="neutral">Not started</StatusBadge>;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 text-sm font-medium">{children}</div>
    </div>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="whitespace-pre-line">{children}</dd>
    </div>
  );
}

export function HistorySection({ car }: { car: Car }) {
  const history = useCarHistory(car.id);
  const actionNumber = new Map(car.actionItems.map((a) => [a.id, a.position]));
  return (
    <StepSection title="Activity and audit trail" description="Every change to the CAR and its actions, oldest first.">
      {history.isError ? (
        <p className="text-sm text-destructive">Could not load the history.</p>
      ) : !history.data ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : history.data.events.length === 0 ? (
        <p className="text-sm text-muted-foreground">No recorded changes.</p>
      ) : (
        <ol className="space-y-3">
          {history.data.events.map((event, index) => (
            <li key={`${event.changeSetId}-${index}`} className="text-sm">
              <p className="font-medium">
                {event.entity === "action"
                  ? `Action ${actionNumber.get(event.actionId ?? 0) ?? ""} ${event.action === "create" ? "added" : "updated"}`
                  : event.action === "create"
                    ? "CAR created"
                    : "CAR updated"}{" "}
                <span className="font-normal text-muted-foreground">
                  {formatTimestamp(event.occurredAt)} by {event.actorName}
                </span>
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {historyChanges(event).map((change) => (
                  <li key={change.field}>
                    <span className="font-medium text-foreground">{change.field}:</span>{" "}
                    {event.action === "create" ? change.to : `${change.from} → ${change.to}`}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </StepSection>
  );
}
