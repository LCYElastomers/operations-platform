"use client";

import { FilterSelect } from "@/components/common/filter-bar";

import { reportingYearOptions } from "./grid";

type ReportingYearSelectProps = {
  year: number;
  onChange: (year: number) => void;
  /** The Baytown year: always offered, even before it has any records. */
  currentYear: number;
  /** The module's earliest reporting year. */
  firstYear: number;
  yearsWithData?: number[];
  disabled?: boolean;
};

export function ReportingYearSelect({
  year,
  onChange,
  currentYear,
  firstYear,
  yearsWithData = [],
  disabled,
}: ReportingYearSelectProps) {
  const options = reportingYearOptions(currentYear, [...yearsWithData, year], firstYear);

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
