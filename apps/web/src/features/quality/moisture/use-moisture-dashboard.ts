"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useDebouncedValue } from "@/hooks/use-debounced-value";

import {
  EMPTY_FILTERS,
  fetchMoistureFilters,
  fetchMoistureLots,
  fetchMoistureTrends,
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

  const lots = useQuery({
    queryKey: moistureKeys.lots(query),
    queryFn: ({ signal }) => fetchMoistureLots(query, signal),
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
    void lots.refetch();
    void trends.refetch();
  };

  return {
    filters,
    setFilter,
    resetFilters,
    invalidDateRange,
    filterOptions,
    lots,
    trends,
    retry,
    dataSource: lots.data?.dataSource ?? trends.data?.dataSource ?? filterOptions.data?.dataSource,
    isUpdating: (lots.isFetching || trends.isFetching) && !lots.isPending && !trends.isPending,
  };
}
