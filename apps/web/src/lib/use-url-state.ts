"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Page state kept in the URL query string, so refresh, bookmarks and
 * Back / Forward restore it. Discrete choices push a history entry; typing
 * (`{ replace: true }`) replaces the current one.
 */
export function useUrlState<T>(
  initial: T,
  parse: (params: URLSearchParams) => T,
  write: (params: URLSearchParams, value: T) => void,
): [T, (next: T, options?: { replace?: boolean }) => void] {
  const [value, setValue] = useState(initial);
  const reader = useRef(parse);

  useEffect(() => {
    reader.current = parse;
  }, [parse]);

  useEffect(() => {
    const onPopState = () => setValue(reader.current(new URLSearchParams(window.location.search)));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const update = useCallback(
    (next: T, options?: { replace?: boolean }) => {
      setValue(next);
      const url = new URL(window.location.href);
      write(url.searchParams, next);
      if (url.href === window.location.href) return;
      if (options?.replace) window.history.replaceState(window.history.state, "", url);
      else window.history.pushState(window.history.state, "", url);
    },
    [write],
  );

  return [value, update];
}
