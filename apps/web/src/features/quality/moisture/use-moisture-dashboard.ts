"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useDebouncedValue } from "@/hooks/use-debounced-value";

import {
  EMPTY_FILTERS,
  fetchMoistureFilters,
  fetchMoistureTrends,
  fetchRecentMoisture,
  isDateRangeInvalid,
  moistureKeys,
  toQueryString,
  type MoistureFilters,
} from "./api";

const SEARCH_DEBOUNCE_MS = 300;

/** Owns filter state and every moisture query for the dashboard. */
export function useMoistureDashboard() {
  const [filters, setFilters] = useState<MoistureFilters>(EMPTY_FILTERS);
  const debouncedSearch = useDebouncedValue(filters.search, SEARCH_DEBOUNCE_MS);

  const invalidDateRange = isDateRangeInvalid(filters);
  const query = toQueryString({ ...filters, search: debouncedSearch });

  const filterOptions = useQuery({
    queryKey: moistureKeys.filters(),
    queryFn: ({ signal }) => fetchMoistureFilters(signal),
    staleTime: 5 * 60_000,
  });

  const recent = useQuery({
    queryKey: moistureKeys.recent(query),
    queryFn: ({ signal }) => fetchRecentMoisture(query, signal),
    placeholderData: keepPreviousData,
    enabled: !invalidDateRange,
  });

  const trends = useQuery({
    queryKey: moistureKeys.trends(query),
    queryFn: ({ signal }) => fetchMoistureTrends(query, signal),
    placeholderData: keepPreviousData,
    enabled: !invalidDateRange,
  });

  const setFilter = <K extends keyof MoistureFilters>(key: K, value: MoistureFilters[K]) =>
    setFilters((current) => ({ ...current, [key]: value }));

  const resetFilters = () => setFilters(EMPTY_FILTERS);

  const retry = () => {
    if (filterOptions.isError) void filterOptions.refetch();
    void recent.refetch();
    void trends.refetch();
  };

  return {
    filters,
    setFilter,
    resetFilters,
    invalidDateRange,
    filterOptions,
    recent,
    trends,
    retry,
    dataSource: recent.data?.dataSource ?? trends.data?.dataSource ?? filterOptions.data?.dataSource,
    isUpdating: (recent.isFetching || trends.isFetching) && !recent.isPending && !trends.isPending,
  };
}
