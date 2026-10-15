"use client";

import { AlertTriangle } from "lucide-react";
import { useId } from "react";

import { cn } from "@/lib/utils";

import type { DetailCode, IncidentRecord, RecordOptionsResponse } from "./api";
import {
  allowedDamageKinds,
  SECTIONS,
  visibleSections,
  type ConditionalKind,
  type DamageDraft,
  type DetailDraft,
  type LopcDraft,
  type PitDraft,
  type RiskDraft,
  type Tri,
} from "./detail-data";
import { Field, fieldClasses } from "./form-fields";

type Problems = Record<string, string | undefined>;

const control = cn(fieldClasses, "h-9 pointer-coarse:h-11");

/** Active codes, plus the stored one so an unchanged inactive value stays valid. */
function codeChoices(codes: DetailCode[] | undefined, current: string) {
  return (codes ?? []).filter((code) => code.active || code.code === current);
}

type InputProps = {
  id: string;
  name: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  problems: Problems;
  hint?: string;
};

function describedBy(id: string, error: string | undefined, hint: string | undefined) {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

function TextInput({ id, name, label, value, onChange, problems, hint, maxLength, inputMode }: InputProps & {
  maxLength: number;
  inputMode?: "decimal";
}) {
  const error = problems[name];
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        value={value}
        maxLength={maxLength}
        inputMode={inputMode}
        autoComplete="off"
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        className={control}
      />
    </Field>
  );
}

function TextArea({ id, name, label, value, onChange, problems, hint }: InputProps) {
  const error = problems[name];
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <textarea
        id={id}
        rows={3}
        maxLength={2000}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        className={cn(fieldClasses, "py-2")}
      />
    </Field>
  );
}

function CodeSelect({ id, name, label, value, onChange, problems, hint, codes, allowed }: InputProps & {
  codes: DetailCode[] | undefined;
  allowed?: string[];
}) {
  const error = problems[name];
  const listed = codeChoices(codes, value).filter((code) => !allowed || allowed.includes(code.code) || code.code === value);
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        className={control}
      >
        <option value="">Not recorded</option>
        {listed.map((code) => (
          <option key={code.code} value={code.code}>
            {code.name}
            {code.active ? "" : " (inactive)"}
          </option>
        ))}
      </select>
    </Field>
  );
}

/** Unknown stays distinct from No (and from Not Applicable, where a taxonomy has one). */
function TriSelect({ id, name, label, value, onChange, problems, hint, unknown = "Unknown" }: Omit<InputProps, "value" | "onChange"> & {
  value: Tri;
  onChange: (value: Tri) => void;
  unknown?: string;
}) {
  const error = problems[name];
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value as Tri)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        className={control}
      >
        <option value="">{unknown}</option>
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </select>
    </Field>
  );
}

function Section({ title, children, problem }: { title: string; children: React.ReactNode; problem?: string }) {
  return (
    <fieldset className="space-y-3 rounded-lg border bg-card p-3">
      <legend className="px-1 text-sm font-semibold">{title}</legend>
      {problem && (
        <p role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

/**
 * Further classifications and the details they allow. Values typed into a section
 * stay in the draft when its classification is deselected, so choosing it again
 * restores them; they are not sent while the section is hidden.
 */
export function DetailSections({
  draft,
  onChange,
  primaryId,
  codes,
  options,
  record,
  problems,
}: {
  draft: DetailDraft;
  onChange: (draft: DetailDraft) => void;
  primaryId: number | null;
  codes: Set<string>;
  options: RecordOptionsResponse | undefined;
  record: IncidentRecord | null;
  problems: Problems;
}) {
  const id = useId();
  const shown = visibleSections(codes);
  const taxonomy = (name: string) => options?.detailCodes?.[name];
  const lopc = <K extends keyof LopcDraft>(key: K) => (value: LopcDraft[K]) =>
    onChange({ ...draft, lopc: { ...draft.lopc, [key]: value } });
  const damage = <K extends keyof DamageDraft>(key: K) => (value: DamageDraft[K]) =>
    onChange({ ...draft, damage: { ...draft.damage, [key]: value } });
  const pit = <K extends keyof PitDraft>(key: K) => (value: PitDraft[K]) =>
    onChange({ ...draft, pit: { ...draft.pit, [key]: value } });
  const risk = <K extends keyof RiskDraft>(key: K) => (value: RiskDraft[K]) =>
    onChange({ ...draft, risk: { ...draft.risk, [key]: value } });
  const field = (section: string, key: string) => ({ id: `${id}-${section}-${key}`, name: `${section}.${key}`, problems });

  const additionalChoices = (options?.classifications ?? []).filter(
    (option) => option.id !== primaryId && (option.active || draft.additional.includes(option.id)),
  );
  const toggle = (optionId: number, checked: boolean) =>
    onChange({
      ...draft,
      additional: checked ? [...draft.additional, optionId] : draft.additional.filter((value) => value !== optionId),
    });

  const orphaned = (Object.keys(SECTIONS) as ConditionalKind[]).filter(
    (kind) => !shown[kind] && record?.[SECTIONS[kind].field],
  );

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2" aria-describedby={`${id}-additional-hint`}>
        <legend className="text-sm font-medium">Additional classifications (optional)</legend>
        <p id={`${id}-additional-hint`} className="text-xs text-muted-foreground">
          One event can carry more than one classification, for example a PIT accident that also damaged property.
        </p>
        {problems.additionalClassificationIds && (
          <p role="alert" className="text-xs text-destructive">
            {problems.additionalClassificationIds}
          </p>
        )}
        <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
          {additionalChoices.map((option) => (
            <label key={option.id} className="flex min-h-8 items-center gap-2 text-sm pointer-coarse:min-h-11">
              <input
                type="checkbox"
                checked={draft.additional.includes(option.id)}
                onChange={(event) => toggle(option.id, event.target.checked)}
                className="size-4 accent-primary"
              />
              {option.name}
              {option.active ? "" : " (inactive)"}
            </label>
          ))}
        </div>
      </fieldset>

      {orphaned.map((kind) => (
        <div
          key={kind}
          role="alert"
          className="space-y-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
        >
          <p className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            This record has stored {SECTIONS[kind].label.toLowerCase()}, which need {SECTIONS[kind].requirement}. Choose
            that classification again to keep them, or remove them when saving.
          </p>
          <label className="flex min-h-8 items-center gap-2 pointer-coarse:min-h-11">
            <input
              type="checkbox"
              checked={draft.remove[kind]}
              onChange={(event) => onChange({ ...draft, remove: { ...draft.remove, [kind]: event.target.checked } })}
              className="size-4 accent-primary"
            />
            Remove the stored {SECTIONS[kind].label.toLowerCase()} when saving
          </label>
        </div>
      ))}

      {shown.lopc && (
        <Section title={SECTIONS.lopc.label} problem={problems.lopcDetails}>
          <TriSelect
            {...field("lopcDetails", "isLopc")}
            label="Loss of primary containment"
            value={draft.lopc.isLopc}
            onChange={lopc("isLopc")}
          />
          <TriSelect
            {...field("lopcDetails", "processSafetyIncident")}
            label="Process safety incident"
            value={draft.lopc.processSafetyIncident}
            onChange={lopc("processSafetyIncident")}
          />
          <TextInput
            {...field("lopcDetails", "materialName")}
            label="Material released"
            maxLength={200}
            value={draft.lopc.materialName}
            onChange={lopc("materialName")}
          />
          <TextInput
            {...field("lopcDetails", "equipmentTag")}
            label="Equipment tag"
            maxLength={100}
            value={draft.lopc.equipmentTag}
            onChange={lopc("equipmentTag")}
          />
          <TextInput
            {...field("lopcDetails", "estimatedQuantity")}
            label="Estimated quantity"
            hint="Leave blank when not known; 0 means nothing was released."
            maxLength={16}
            inputMode="decimal"
            value={draft.lopc.estimatedQuantity}
            onChange={lopc("estimatedQuantity")}
          />
          <CodeSelect
            {...field("lopcDetails", "quantityUnitCode")}
            label="Quantity unit"
            codes={taxonomy("quantity_unit")}
            value={draft.lopc.quantityUnitCode}
            onChange={lopc("quantityUnitCode")}
          />
          <CodeSelect
            {...field("lopcDetails", "failureMechanismCode")}
            label="Failure mechanism"
            codes={taxonomy("lopc_failure_mechanism")}
            value={draft.lopc.failureMechanismCode}
            onChange={lopc("failureMechanismCode")}
          />
          <CodeSelect
            {...field("lopcDetails", "contributingFactorCode")}
            label="Contributing factor"
            codes={taxonomy("lopc_contributing_factor")}
            value={draft.lopc.contributingFactorCode}
            onChange={lopc("contributingFactorCode")}
          />
          <CodeSelect
            {...field("lopcDetails", "secondaryContainmentStatusCode")}
            label="Secondary containment"
            codes={taxonomy("secondary_containment_status")}
            value={draft.lopc.secondaryContainmentStatusCode}
            onChange={lopc("secondaryContainmentStatusCode")}
          />
          <div className="sm:col-span-2">
            <TextArea {...field("lopcDetails", "notes")} label="Notes" value={draft.lopc.notes} onChange={lopc("notes")} />
          </div>
        </Section>
      )}

      {shown.damage && (
        <Section title={SECTIONS.damage.label} problem={problems.damageDetails}>
          <CodeSelect
            {...field("damageDetails", "damageKindCode")}
            label="Damage kind"
            codes={taxonomy("damage_kind")}
            allowed={allowedDamageKinds(codes)}
            value={draft.damage.damageKindCode}
            onChange={damage("damageKindCode")}
          />
          <TextInput
            {...field("damageDetails", "assetOrPropertyName")}
            label="Asset or property"
            maxLength={200}
            value={draft.damage.assetOrPropertyName}
            onChange={damage("assetOrPropertyName")}
          />
          <TextInput
            {...field("damageDetails", "equipmentTag")}
            label="Equipment tag"
            maxLength={100}
            value={draft.damage.equipmentTag}
            onChange={damage("equipmentTag")}
          />
          <TextInput
            {...field("damageDetails", "assetType")}
            label="Asset type"
            maxLength={100}
            value={draft.damage.assetType}
            onChange={damage("assetType")}
          />
          <TextInput
            {...field("damageDetails", "estimatedCost")}
            label="Estimated cost"
            hint="Leave blank when not known."
            maxLength={16}
            inputMode="decimal"
            value={draft.damage.estimatedCost}
            onChange={damage("estimatedCost")}
          />
          <CodeSelect
            {...field("damageDetails", "currencyCode")}
            label="Currency"
            codes={taxonomy("currency")}
            value={draft.damage.currencyCode}
            onChange={damage("currencyCode")}
          />
          <TextInput
            {...field("damageDetails", "workOrderReference")}
            label="Work order"
            maxLength={100}
            value={draft.damage.workOrderReference}
            onChange={damage("workOrderReference")}
          />
          <TriSelect
            {...field("damageDetails", "outOfService")}
            label="Out of service"
            value={draft.damage.outOfService}
            onChange={damage("outOfService")}
          />
          <TriSelect
            {...field("damageDetails", "repairRequired")}
            label="Repair required"
            value={draft.damage.repairRequired}
            onChange={damage("repairRequired")}
          />
          <div className="sm:col-span-2 grid gap-3">
            <TextArea
              {...field("damageDetails", "damageDescription")}
              label="Damage description"
              value={draft.damage.damageDescription}
              onChange={damage("damageDescription")}
            />
            <TextArea
              {...field("damageDetails", "operationalImpact")}
              label="Operational impact"
              value={draft.damage.operationalImpact}
              onChange={damage("operationalImpact")}
            />
            <TextArea {...field("damageDetails", "notes")} label="Notes" value={draft.damage.notes} onChange={damage("notes")} />
          </div>
        </Section>
      )}

      {shown.pit && (
        <Section title={SECTIONS.pit.label} problem={problems.pitDetails}>
          <TextInput
            {...field("pitDetails", "vehicleIdentifier")}
            label="Vehicle identifier"
            maxLength={100}
            value={draft.pit.vehicleIdentifier}
            onChange={pit("vehicleIdentifier")}
          />
          <TextInput
            {...field("pitDetails", "vehicleType")}
            label="Vehicle type"
            maxLength={100}
            value={draft.pit.vehicleType}
            onChange={pit("vehicleType")}
          />
          <CodeSelect
            {...field("pitDetails", "ownershipTypeCode")}
            label="Ownership"
            codes={taxonomy("pit_ownership")}
            value={draft.pit.ownershipTypeCode}
            onChange={pit("ownershipTypeCode")}
          />
          <TextInput
            {...field("pitDetails", "operatingCompany")}
            label="Operating company"
            maxLength={200}
            value={draft.pit.operatingCompany}
            onChange={pit("operatingCompany")}
          />
          <TextInput
            {...field("pitDetails", "impactedAssetOrProperty")}
            label="Impacted asset or property"
            maxLength={200}
            value={draft.pit.impactedAssetOrProperty}
            onChange={pit("impactedAssetOrProperty")}
          />
          <TriSelect
            {...field("pitDetails", "damageOccurred")}
            label="Damage occurred"
            value={draft.pit.damageOccurred}
            onChange={pit("damageOccurred")}
          />
          <div className="sm:col-span-2">
            <TextArea {...field("pitDetails", "notes")} label="Notes" value={draft.pit.notes} onChange={pit("notes")} />
          </div>
        </Section>
      )}

      <Section title="Serious risk (PSIF)" problem={problems.seriousRiskDetails}>
        <TriSelect
          {...field("seriousRiskDetails", "isPsif")}
          label="Potential serious injury or fatality (PSIF)"
          unknown="Not assessed"
          hint="Not assessed is different from No."
          value={draft.risk.isPsif}
          onChange={risk("isPsif")}
        />
        {draft.risk.isPsif === "yes" && (
          <>
            <CodeSelect
              {...field("seriousRiskDetails", "potentialSeverityCode")}
              label="Potential severity"
              codes={taxonomy("potential_severity")}
              value={draft.risk.potentialSeverityCode}
              onChange={risk("potentialSeverityCode")}
            />
            <CodeSelect
              {...field("seriousRiskDetails", "seriousRiskCategoryCode")}
              label="Serious-risk category"
              codes={taxonomy("serious_risk_category")}
              value={draft.risk.seriousRiskCategoryCode}
              onChange={risk("seriousRiskCategoryCode")}
            />
          </>
        )}
        {draft.risk.isPsif !== "" && (
          <div className="sm:col-span-2">
            <TextArea
              {...field("seriousRiskDetails", "rationale")}
              label="Rationale"
              value={draft.risk.rationale}
              onChange={risk("rationale")}
            />
          </div>
        )}
      </Section>
    </div>
  );
}
