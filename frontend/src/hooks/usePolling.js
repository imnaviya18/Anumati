import { useCallback, useEffect, useState } from "react";

/**
 * Authenticated polling hook with visible "data as of" timestamp
 * Source: Problem Statement Section B ("Real-time" means authenticated polling at a configurable interval with a visible "data as of" timestamp) & Sheet 01 Block 07
 */
export function usePolling(fetcher, intervalMs = 15000) {
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((v) => v + 1), []);
  const [data, setData] = useState(null);
  const [dataAsOf, setDataAsOf] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    window.addEventListener("anumati:data-changed", refresh);
    return () => window.removeEventListener("anumati:data-changed", refresh);
  }, [refresh]);
  useEffect(() => {
    let mounted = true;

    async function poll() {
      try {
        const result = await fetcher();
        if (mounted) {
          setData(result);
          setDataAsOf(result?.data_as_of || new Date().toISOString());
          setError(null);
          setLoading(false);
        }
      } catch (err) {
        if (mounted) {
          setError(err);
          setLoading(false);
        }
      }
    }

    poll();
    const timer = setInterval(poll, intervalMs);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [fetcher, intervalMs, revision]);

  return { data, dataAsOf, loading, error, refresh };
}
