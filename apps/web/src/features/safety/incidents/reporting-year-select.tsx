"use client";

import { FilterSelect } from "@/components/common/filter-bar";

import { reportingYearOptions } from "./grid";

type ReportingYearSelectProps = {
  year: number;
  onChange: (year: number) => void;
  yearsWithData?: number[];
  disabled?: boolean;
};

export function ReportingYearSelect({
  year,
  onChange,
  yearsWithData = [],
  disabled,
}: ReportingYearSelectProps) {
  const options = reportingYearOptions(new Date().getFullYear(), [...yearsWithData, year]);

  return (
    <FilterSelect
      label="Reporting year"
      placeholder={false}
      options={options.map((value) => ({ value: String(value), label: String(value) }))}
      value={String(year)}
      onChange={(event) => onChange(Number(event.target.value))}
      disabled={disabled}
      className="pointer-coarse:h-11"
    />
  );
}
