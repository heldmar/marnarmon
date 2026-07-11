import { useEffect, useMemo, useRef, useState } from "react";
import { config } from "../config.js";
import { getDockerLogs } from "../api.js";
import { usePolling } from "../hooks/usePolling.js";
import { fmtLogTime } from "../format.js";

const TAIL_OPTIONS = [100, 500, 1000];

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

// Cheap client-side severity tint for a container log line — docker logs carry
// no structured level, so scan the text (best-effort, purely cosmetic).
function severityClass(msg) {
  const s = msg.toLowerCase();
  if (/\b(error|err|fail|failed|fatal|panic|exception)\b/.test(s)) return "m-err";
  if (/\b(warn|warning|deprecat)\b/.test(s)) return "m-warn";
  if (/\b(ready|started|listening|success|healthy|online)\b/.test(s)) return "m-ok";
  return "m-info";
}

// Right-side slide-over showing one container's live log tail
// (DOCKER_MONITOR_SPEC.md §7). Owns its own search / tail size / Live toggle and
// its own poll, independent of the page-level Live toggle. Buffered lines are
// capped by `tail` (each poll REPLACES the buffer — no unbounded growth).
export default function ContainerLogs({ open, container, onClose }) {
  const [search, setSearch] = useState("");
  const [tail, setTail] = useState(500);
  const [live, setLive] = useState(true);

  const termRef = useRef(null);
  const closeRef = useRef(null);
  const restoreFocusRef = useRef(null);

  const name = container?.name;

  const poll = usePolling(
    () =>
      open && name
        ? getDockerLogs(name, { tail })
        : Promise.resolve({ lines: [] }),
    config.dockerRefreshSeconds * 1000,
    [open, name, tail],
    { enabled: open && live }
  );

  const lines = useMemo(() => {
    const all = poll.data?.lines || [];
    const q = search.trim().toLowerCase();
    if (!q) return all;
    return all.filter((l) => (l.message || "").toLowerCase().includes(q));
  }, [poll.data, search]);

  // Auto-scroll to the newest line while streaming.
  useEffect(() => {
    if (live && termRef.current) {
      termRef.current.scrollTop = termRef.current.scrollHeight;
    }
  }, [lines, live]);

  // Focus management: move focus into the drawer on open, restore it on close.
  useEffect(() => {
    if (open) {
      restoreFocusRef.current = document.activeElement;
      closeRef.current?.focus();
    } else if (restoreFocusRef.current) {
      restoreFocusRef.current.focus?.();
      restoreFocusRef.current = null;
    }
  }, [open]);

  // Escape closes.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div
      className={`drawer-scrim${open ? " open" : ""}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="drawer" role="dialog" aria-label="Container logs">
        <div className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <div className="dh-title">{container?.name || "—"}</div>
            <div className="dh-sub">
              stack: {container?.stack || "—"} · image: {container?.image || "—"}
            </div>
          </div>
          <div className="drawer-spacer" />
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
            ref={closeRef}
            className="icon-btn"
            onClick={onClose}
            aria-label="Close logs"
          >
            ✕
          </button>
        </div>

        <div className="drawer-toolbar">
          <div className="search">
            <span className="search-icon">{SearchIcon}</span>
            <input
              className="input"
              type="search"
              placeholder="Filter this container's log lines…"
              aria-label="Filter log lines"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="seg" role="group" aria-label="Tail size">
            {TAIL_OPTIONS.map((n) => (
              <button
                key={n}
                className={tail === n ? "active" : ""}
                onClick={() => setTail(n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        <div className="term" ref={termRef}>
          {poll.error && !lines.length ? (
            <div className="muted">Could not load logs: {poll.error}</div>
          ) : !lines.length ? (
            <div className="muted">
              {poll.loading ? "Loading logs…" : "No log lines."}
            </div>
          ) : (
            lines.map((l, i) => (
              <div className="lrow" key={i}>
                <span className="lts">{l.ts ? fmtLogTime(l.ts) : "—"}</span>
                <span className="lmsg">
                  <span className={severityClass(l.message || "")}>
                    {l.message}
                  </span>
                </span>
              </div>
            ))
          )}
        </div>

        <div className="drawer-foot">
          <span>
            Showing last {tail} lines · {live ? "streaming" : "paused"}
          </span>
          <span>timestamps in local time</span>
        </div>
      </aside>
    </div>
  );
}
