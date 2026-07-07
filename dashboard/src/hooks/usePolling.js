import { useCallback, useEffect, useRef, useState } from "react";

// Calls async `fn` immediately and then every `intervalMs`. Re-runs when any
// value in `deps` changes (e.g. the selected history window). Keeps the last
// good data on error so the UI doesn't blank out on a transient failure.
// When `enabled` is false the interval is skipped, but a `tick()` still fires on
// mount and on every deps change so filter edits refetch immediately.
export function usePolling(fn, intervalMs, deps = [], { enabled = true } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [errorCode, setErrorCode] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  const savedFn = useRef(fn);
  savedFn.current = fn;

  const tick = useCallback(async () => {
    try {
      const d = await savedFn.current();
      setData(d);
      setError(null);
      setErrorCode(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e.message || String(e));
      setErrorCode(e.code || null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    tick();
    if (!enabled) return;
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, tick, enabled, ...deps]);

  return { data, error, errorCode, loading, lastUpdated, refresh: tick };
}
