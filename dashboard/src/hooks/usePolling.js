import { useCallback, useEffect, useRef, useState } from "react";

// Calls async `fn` immediately and then every `intervalMs`. Re-runs when any
// value in `deps` changes (e.g. the selected history window). Keeps the last
// good data on error so the UI doesn't blank out on a transient failure.
export function usePolling(fn, intervalMs, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  const savedFn = useRef(fn);
  savedFn.current = fn;

  const tick = useCallback(async () => {
    try {
      const d = await savedFn.current();
      setData(d);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    tick();
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, tick, ...deps]);

  return { data, error, loading, lastUpdated, refresh: tick };
}
