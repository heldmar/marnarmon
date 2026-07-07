import { useEffect, useMemo, useState } from "react";
import { config } from "../config.js";
import { getLogs, getLogSources } from "../api.js";
import { usePolling } from "../hooks/usePolling.js";
import { fmtClock } from "../format.js";
import Header from "../components/Header.jsx";
import SegmentedControl from "../components/SegmentedControl.jsx";
import TimeRangeControl from "../components/TimeRangeControl.jsx";
import SourcePicker from "../components/SourcePicker.jsx";
import LogList from "../components/LogList.jsx";

const SEVERITY_OPTIONS = [
  { label: "Errors", value: "errors" },
  { label: "Warnings", value: "warnings" },
  { label: "Info", value: "info" },
  { label: "Everything", value: "all" },
];

const LIMIT = 200;

const SearchIcon = (
  <svg
    viewBox="0 0 24 24"
    width="15"
    height="15"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  </svg>
);

const RefreshIcon = (
  <svg
    viewBox="0 0 24 24"
    width="15"
    height="15"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M4 12a8 8 0 0 1 13.7-5.6L20 8" />
    <path d="M20 4v4h-4" />
    <path d="M20 12a8 8 0 0 1-13.7 5.6L4 16" />
    <path d="M4 20v-4h4" />
  </svg>
);

export default function LogsView({ health, theme, onToggleTheme }) {
  const [severity, setSeverity] = useState("all");
  const [range, setRange] = useState({ window: "24h" });
  const [units, setUnits] = useState([]);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [live, setLive] = useState(false);

  const sources = usePolling(getLogSources, 0, [], { enabled: false });
  const sourceList = sources.data?.sources || [];

  // Debounce the keyword search so we don't fire a request per keystroke.
  useEffect(() => {
    const id = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  const filters = useMemo(() => {
    const base = { severity, limit: LIMIT, units };
    if (q) base.q = q;
    if (range.custom) {
      base.since = range.since;
      base.until = range.until;
    } else {
      base.window = range.window;
    }
    return base;
  }, [severity, range, units, q]);

  const key = JSON.stringify(filters);
  const poll = usePolling(() => getLogs(filters), config.logsRefreshSeconds * 1000, [key], {
    enabled: live,
  });

  const [older, setOlder] = useState([]);
  const [moreTruncated, setMoreTruncated] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(null);

  // Reset the appended "load older" pages whenever the filters change.
  useEffect(() => {
    setOlder([]);
    setMoreTruncated(true);
    setMoreError(null);
  }, [key]);

  const lines = useMemo(() => {
    const head = poll.data?.lines || [];
    const seen = new Set();
    const out = [];
    for (const l of [...head, ...older]) {
      if (seen.has(l.cursor)) continue;
      seen.add(l.cursor);
      out.push(l);
    }
    return out;
  }, [poll.data, older]);

  const spansDays = useMemo(() => {
    if (lines.length < 2) return false;
    const day = (ts) => Math.floor(new Date(ts * 1000).setHours(0, 0, 0, 0));
    return day(lines[0].ts) !== day(lines[lines.length - 1].ts);
  }, [lines]);

  const truncated = older.length ? moreTruncated : !!poll.data?.truncated;

  async function loadMore() {
    const oldest = lines[lines.length - 1];
    if (!oldest) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const res = await getLogs({
        ...filters,
        until: oldest.ts,
        exclude_cursor: oldest.cursor,
      });
      setOlder((prev) => [...prev, ...(res.lines || [])]);
      setMoreTruncated(!!res.truncated);
    } catch (e) {
      setMoreError(e.message || String(e));
    } finally {
      setLoadingMore(false);
    }
  }

  const disabled = poll.errorCode === "logs_disabled";

  return (
    <>
      <Header
        host={health.data?.host}
        health={health.data}
        error={health.error}
        lastUpdated={poll.lastUpdated}
        theme={theme}
        onToggleTheme={onToggleTheme}
        onRefresh={() => {
          poll.refresh();
          health.refresh();
        }}
      />

      <div className="card logs-toolbar">
        <div className="toolbar-row">
          <div className="search">
            <span className="search-icon">{SearchIcon}</span>
            <input
              className="input"
              type="search"
              placeholder="Search log messages…"
              aria-label="Search log messages"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="toolbar-spacer" />
          <button
            className={`btn${live ? " active" : ""}`}
            onClick={() => setLive((v) => !v)}
            aria-pressed={live}
            title={live ? "Live updates on" : "Live updates off"}
            aria-label="Toggle live updates"
          >
            <span className="live-dot" />
            Live
          </button>
          <button
            className="btn btn-icon"
            onClick={() => poll.refresh()}
            title="Refresh now"
            aria-label="Refresh logs now"
          >
            {RefreshIcon}
          </button>
          {poll.lastUpdated ? (
            <span className="updated">Updated {fmtClock(poll.lastUpdated)}</span>
          ) : null}
        </div>

        <div className="toolbar-row">
          <div className="field">
            <span className="field-label">Severity</span>
            <SegmentedControl
              options={SEVERITY_OPTIONS}
              value={severity}
              onChange={setSeverity}
              ariaLabel="Severity filter"
            />
          </div>
          <div className="field">
            <span className="field-label">Time range</span>
            <TimeRangeControl value={range} onChange={setRange} />
          </div>
          <div className="field">
            <span className="field-label">Sources</span>
            <SourcePicker
              sources={sourceList}
              selected={units}
              onChange={setUnits}
            />
          </div>
        </div>

        {units.length ? (
          <div className="chips">
            {units.map((u) => {
              const src = sourceList.find((s) => s.unit === u);
              return (
                <span key={u} className="chip">
                  {src?.label || u}
                  <button
                    onClick={() => setUnits(units.filter((x) => x !== u))}
                    aria-label={`Remove ${src?.label || u}`}
                    title="Remove"
                  >
                    ×
                  </button>
                </span>
              );
            })}
          </div>
        ) : null}
      </div>

      {disabled ? (
        <div className="center-msg">Server Logs isn't enabled on this host.</div>
      ) : poll.error && !lines.length ? (
        <div className="banner error">Could not load logs: {poll.error}</div>
      ) : poll.loading && !poll.data ? (
        <div className="center-msg">Loading logs…</div>
      ) : !lines.length ? (
        <div className="center-msg">No log lines match your filters.</div>
      ) : (
        <div className="card logs-results">
          <LogList lines={lines} spansDays={spansDays} />
          {moreError ? (
            <div className="banner error" style={{ marginTop: 12 }}>
              Could not load more: {moreError}
            </div>
          ) : null}
          {truncated ? (
            <div className="log-more">
              <button className="btn" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load older lines"}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}
