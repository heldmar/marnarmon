import { fmtClock } from "../format.js";

function HealthPill({ health, error }) {
  let cls = "pill";
  let label = "Connecting…";
  if (error) {
    cls += " error";
    label = "Unreachable";
  } else if (health) {
    if (health.status === "ok") {
      cls += " ok";
      label = "Online";
    } else {
      cls += " stale";
      label = "Stale data";
    }
  }
  return (
    <span className={cls}>
      <span className="led" />
      {label}
    </span>
  );
}

export default function Header({
  host,
  health,
  error,
  lastUpdated,
  theme,
  onToggleTheme,
  onRefresh,
}) {
  return (
    <header className="header">
      <div className="brand">
        <span className="dot" />
        <div>
          <h1>MarNarMon</h1>
          <div className="host">{host || "—"}</div>
        </div>
      </div>
      <div className="header-actions">
        <HealthPill health={health} error={error} />
        {lastUpdated ? (
          <span className="updated">Updated {fmtClock(lastUpdated)}</span>
        ) : null}
        <button
          className="btn btn-icon"
          onClick={onRefresh}
          title="Refresh now"
          aria-label="Refresh now"
        >
          ↻
        </button>
        <button
          className="btn btn-icon"
          onClick={onToggleTheme}
          title="Toggle theme"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>
    </header>
  );
}
