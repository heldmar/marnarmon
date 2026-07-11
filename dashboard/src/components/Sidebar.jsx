// Fixed vertical icon rail. Hand-drawn stroke SVG icons in the Gauge.jsx style.
// Each button carries a keyboard-reachable `.tip` flyout (hover + focus).
const ResourcesIcon = (
  <svg
    viewBox="0 0 24 24"
    width="22"
    height="22"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M3.5 16.5a8.5 8.5 0 0 1 17 0" />
    <path d="M12 16.5l4.2-4.2" />
    <circle cx="12" cy="16.5" r="1.15" fill="currentColor" stroke="none" />
  </svg>
);

const LogsIcon = (
  <svg
    viewBox="0 0 24 24"
    width="22"
    height="22"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <rect x="4" y="3" width="16" height="18" rx="2.5" />
    <path d="M8 8h8" />
    <path d="M8 12h8" />
    <path d="M8 16h5" />
  </svg>
);

// Docker whale + container stack (finer 1.6 stroke — more strokes than the
// other rail icons). Verbatim from DOCKER_MONITOR_SPEC.md §2.2.
const DockerIcon = (
  <svg
    viewBox="0 0 24 24"
    width="22"
    height="22"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {/* container stack */}
    <rect x="4" y="9.5" width="2.6" height="2.4" />
    <rect x="7.2" y="9.5" width="2.6" height="2.4" />
    <rect x="10.4" y="9.5" width="2.6" height="2.4" />
    <rect x="7.2" y="6.8" width="2.6" height="2.4" />
    <rect x="10.4" y="6.8" width="2.6" height="2.4" />
    {/* whale body + wave */}
    <path d="M2.5 12.2h13.2c.9 0 1.7-.5 2.1-1.3.5.9 1.7 1.2 2.5.6-.1 1.9-1.3 4.6-4 5.3-1.1.3-2.2.4-3.3.4-4 0-7.4-2-9-5z" />
    {/* spout */}
    <path d="M19 8.6c.5-.4 1.3-.4 1.8 0-.2.5-.8.8-1.3.7" />
  </svg>
);

export default function Sidebar({ section, onSelect, logsEnabled, dockerEnabled }) {
  const items = [
    {
      id: "resources",
      label: "Server Resources",
      desc: "CPU, memory, disk & network",
      icon: ResourcesIcon,
    },
  ];
  if (logsEnabled) {
    items.push({
      id: "logs",
      label: "Server Logs",
      desc: "Browse the system journal",
      icon: LogsIcon,
    });
  }
  if (dockerEnabled) {
    items.push({
      id: "docker",
      label: "Docker",
      desc: "Containers, stacks & live logs",
      icon: DockerIcon,
    });
  }

  return (
    <nav className="sidebar" aria-label="Sections">
      <span className="sidebar-mark" aria-hidden="true">
        <span className="dot" />
      </span>
      {items.map((it) => {
        const active = section === it.id;
        return (
          <button
            key={it.id}
            className={`sidebar-btn${active ? " active" : ""}`}
            onClick={() => onSelect(it.id)}
            aria-label={it.label}
            aria-current={active ? "page" : undefined}
          >
            {it.icon}
            <span className="tip" role="tooltip">
              <b>{it.label}</b>
              <i>{it.desc}</i>
            </span>
          </button>
        );
      })}
    </nav>
  );
}
