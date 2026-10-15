"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Page state kept in the URL query string, so refresh, bookmarks and
 * Back / Forward restore it. Discrete choices push a history entry; typing
 * (`{ replace: true }`) replaces the current one. A link to the same page
 * with a different query (for example the sidebar link, which has none)
 * re-reads the state, since Next keeps the page mounted.
 */
export function useUrlState<T>(
  initial: T,
  parse: (params: URLSearchParams) => T,
  write: (params: URLSearchParams, value: T) => void,
): [T, (next: T, options?: { replace?: boolean }) => void] {
  const [value, setValue] = useState(initial);
  const reader = useRef(parse);
  const writer = useRef(write);
  const search = useSearchParams()?.toString() ?? null;

  useEffect(() => {
    reader.current = parse;
    writer.current = write;
  }, [parse, write]);

  useEffect(() => {
    const onPopState = () => setValue(reader.current(new URLSearchParams(window.location.search)));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    // Next can report an earlier query after a newer write; only the
    // address bar's current query is authoritative.
    if (search === null || new URLSearchParams(window.location.search).toString() !== search) return;
    setValue((current) => {
      const mine = new URLSearchParams(search);
      writer.current(mine, current);
      return mine.toString() === search ? current : reader.current(new URLSearchParams(search));
    });
  }, [search]);

  const update = useCallback(
    (next: T, options?: { replace?: boolean }) => {
      setValue(next);
      const url = new URL(window.location.href);
      write(url.searchParams, next);
      if (url.href === window.location.href) return;
      // Next ignores history entries that already carry its own state, so
      // pass none and let it attach its state and update `useSearchParams`.
      if (options?.replace) window.history.replaceState(null, "", url);
      else window.history.pushState(null, "", url);
    },
    [write],
  );

  return [value, update];
}
