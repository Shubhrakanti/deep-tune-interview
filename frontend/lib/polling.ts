"use client";

import { useEffect, useRef, useState } from "react";

/**
 * usePolling — fetch on mount and again every `intervalMs` until `stopWhen`
 * returns true (or the component unmounts).
 *
 * Returns { data, error, refresh }. `refresh` triggers an immediate re-fetch.
 *
 * Designed for the simplest possible "is the job done yet" pattern in M2 —
 * no SWR, no cache invalidation, just a loop. Page-level components decide
 * when to stop polling by checking the data.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  stopWhen?: (data: T) => boolean,
): { data: T | null; error: unknown; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const stopRef = useRef(stopWhen);
  stopRef.current = stopWhen;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const next = await fetcherRef.current();
        if (cancelled) return;
        setData(next);
        setError(null);
        const done = stopRef.current?.(next) ?? false;
        if (!done) {
          timer = setTimeout(tick, intervalMs);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e);
        timer = setTimeout(tick, intervalMs);
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs]);

  return {
    data,
    error,
    refresh: () => {
      fetcherRef.current().then(setData).catch(setError);
    },
  };
}

/**
 * Helpful: turn "running" / "queued" into "we should keep polling".
 */
export const stillRunning = (status: string) =>
  status === "queued" || status === "running";
