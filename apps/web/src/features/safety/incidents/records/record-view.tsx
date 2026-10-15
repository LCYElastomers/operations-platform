import { StatusBadge } from "@/components/common/status-badge";

import type { IncidentRecord, RecordOptionsResponse } from "./api";
import { codeNames, yesNo } from "./detail-data";
import { EVENT_LABELS, formatRecordDate, STATUS_LABELS } from "./record-data";

type Row = [label: string, value: string];

const UNKNOWN = "Unknown";

function text(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? UNKNOWN : value;
}

function Rows({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <section aria-label={title} className="rounded-lg border bg-card p-3">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[max-content_1fr]">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className={value === UNKNOWN ? "text-muted-foreground italic" : "break-words whitespace-pre-line"}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** One record and its details, read-only. Missing values read Unknown, never 0 or No. */
export function RecordView({ record, options }: { record: IncidentRecord; options: RecordOptionsResponse | undefined }) {
  const codes = codeNames(options?.detailCodes);
  const code = (value: string | null | undefined) => (value ? (codes.get(value) ?? value) : UNKNOWN);
  const lopc = record.lopcDetails;
  const damage = record.damageDetails;
  const pit = record.pitDetails;
  const risk = record.seriousRiskDetails;
  const further = record.additionalClassifications ?? [];
  const quantity = lopc?.estimatedQuantity != null ? `${lopc.estimatedQuantity} ${code(lopc.quantityUnitCode)}` : UNKNOWN;
  const cost = damage?.estimatedCost != null ? `${damage.estimatedCost} ${code(damage.currencyCode)}` : UNKNOWN;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={record.status === "active" ? "success" : "neutral"}>{STATUS_LABELS[record.status]}</StatusBadge>
        {record.source === "legacy_import" && <StatusBadge tone="info">Imported</StatusBadge>}
      </div>
      <Rows
        title="Record"
        rows={[
          ["Number", text(record.incidentNumber)],
          ["Type", EVENT_LABELS[record.eventType].one],
          ["Date", formatRecordDate(record.incidentDate)],
          ["Area", text(record.areaName)],
          ["Classification", record.classificationName ?? "Unclassified"],
          ["Additional classifications", further.length ? further.map((c) => c.name).join(", ") : "None"],
          ["Description", record.description],
        ]}
      />
      {lopc && (
        <Rows
          title="Spill / Release / LOPC details"
          rows={[
            ["Loss of primary containment", yesNo(lopc.isLopc)],
            ["Process safety incident", yesNo(lopc.processSafetyIncident)],
            ["Material released", text(lopc.materialName)],
            ["Estimated quantity", quantity],
            ["Equipment tag", text(lopc.equipmentTag)],
            ["Failure mechanism", code(lopc.failureMechanismCode)],
            ["Contributing factor", code(lopc.contributingFactorCode)],
            ["Secondary containment", code(lopc.secondaryContainmentStatusCode)],
            ["Notes", text(lopc.notes)],
          ]}
        />
      )}
      {damage && (
        <Rows
          title="Damage / failure details"
          rows={[
            ["Damage kind", code(damage.damageKindCode)],
            ["Asset or property", text(damage.assetOrPropertyName)],
            ["Equipment tag", text(damage.equipmentTag)],
            ["Asset type", text(damage.assetType)],
            ["Estimated cost", cost],
            ["Work order", text(damage.workOrderReference)],
            ["Out of service", yesNo(damage.outOfService)],
            ["Repair required", yesNo(damage.repairRequired)],
            ["Damage description", text(damage.damageDescription)],
            ["Operational impact", text(damage.operationalImpact)],
            ["Notes", text(damage.notes)],
          ]}
        />
      )}
      {pit && (
        <Rows
          title="Powered industrial vehicle details"
          rows={[
            ["Vehicle identifier", text(pit.vehicleIdentifier)],
            ["Vehicle type", text(pit.vehicleType)],
            ["Ownership", code(pit.ownershipTypeCode)],
            ["Operating company", text(pit.operatingCompany)],
            ["Impacted asset or property", text(pit.impactedAssetOrProperty)],
            ["Damage occurred", yesNo(pit.damageOccurred)],
            ["Notes", text(pit.notes)],
          ]}
        />
      )}
      <Rows
        title="Serious risk (PSIF)"
        rows={
          risk
            ? [
                ["PSIF", risk.isPsif ? "Yes" : "No"],
                ...(risk.isPsif
                  ? ([
                      ["Potential severity", code(risk.potentialSeverityCode)],
                      ["Serious-risk category", code(risk.seriousRiskCategoryCode)],
                    ] as Row[])
                  : []),
                ["Rationale", text(risk.rationale)],
              ]
            : [["PSIF", "Not assessed"]]
        }
      />
      {record.status !== "active" && (
        <p className="text-xs text-muted-foreground">
          {STATUS_LABELS[record.status]}: {record.statusReason}
          {record.relatedIncidentNumber && ` · Replaced by ${record.relatedIncidentNumber}`}
        </p>
      )}
    </div>
  );
}
