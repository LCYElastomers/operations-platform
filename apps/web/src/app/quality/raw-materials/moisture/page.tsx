import { AlertTriangle, Droplets, FlaskConical, Layers } from "lucide-react";
import type { Metadata } from "next";

import { DataTable, type DataTableColumn } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { TrendChart } from "@/components/common/trend-chart";
import { getNavItem } from "@/config/navigation";

export const metadata: Metadata = { title: "Moisture Analysis" };

type MoistureSampleRow = {
  sampleId: string;
  material: string;
  lot: string | null;
  sampledAt: string;
  moisturePct: number | null;
  specMaxPct: number | null;
  result: string | null;
};

const columns: DataTableColumn<MoistureSampleRow>[] = [
  { accessorKey: "sampleId", header: "Sample" },
  { accessorKey: "material", header: "Material" },
  { accessorKey: "lot", header: "Lot" },
  { accessorKey: "sampledAt", header: "Sampled" },
  { accessorKey: "moisturePct", header: "Moisture %" },
  { accessorKey: "specMaxPct", header: "Spec max %" },
  { accessorKey: "result", header: "Result" },
];

const NO_SAMPLES: MoistureSampleRow[] = [];
const AWAITING = "Awaiting data source";

export default function MoistureAnalysisPage() {
  const item = getNavItem("/quality/raw-materials/moisture");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Quality · Raw Materials"
        title={item.label}
        description={item.description}
        status={<StatusBadge tone="pending">{AWAITING}</StatusBadge>}
      />

      <FilterBar>
        <FilterSelect label="Period" options={[]} placeholder="All dates" disabled />
        <FilterSelect label="Material" options={[]} placeholder="All materials" disabled />
        <FilterSelect label="Supplier" options={[]} placeholder="All suppliers" disabled />
        <FilterSelect label="Result" options={[]} placeholder="All results" disabled />
      </FilterBar>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Samples" value={null} caption={AWAITING} icon={FlaskConical} />
        <MetricCard
          label="Average moisture"
          value={null}
          unit="%"
          precision={2}
          caption={AWAITING}
          icon={Droplets}
        />
        <MetricCard
          label="Out of specification"
          value={null}
          caption={AWAITING}
          icon={AlertTriangle}
        />
        <MetricCard label="Materials" value={null} caption={AWAITING} icon={Layers} />
      </div>

      <DataTable
        caption="Moisture samples"
        columns={columns}
        data={NO_SAMPLES}
        emptyState={
          <EmptyState
            variant="plain"
            icon={Droplets}
            title="No moisture samples"
            description="Samples will appear here once the moisture data source is connected and synchronized."
          />
        }
      />

      <TrendChart title="Moisture trend" description="Moisture content by sample date" unit="%" series={[]} />
    </div>
  );
}
