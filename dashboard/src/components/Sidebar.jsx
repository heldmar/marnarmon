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
    {/* container stack, centered on the whale's back */}
    <rect x="6.7" y="8.8" width="2.8" height="2.9" rx="0.3" />
    <rect x="9.8" y="8.8" width="2.8" height="2.9" rx="0.3" />
    <rect x="12.9" y="8.8" width="2.8" height="2.9" rx="0.3" />
    <rect x="9.8" y="5.7" width="2.8" height="2.9" rx="0.3" />
    <rect x="12.9" y="5.7" width="2.8" height="2.9" rx="0.3" />
    {/* rounded whale hull carrying the stack */}
    <path d="M3.2 11.9a8 6 0 0 0 16 0z" />
    {/* tail fluke at the stern */}
    <path d="M16.9 11.9c1-.3 1.7-1.2 1.9-2.3.5.5 1.2.7 1.9.6-.2 1.3-1.1 2.4-2.4 2.8" />
    {/* spout at the head */}
    <path d="M5.1 11.5c-.5-.9-.3-2 .5-2.6" />
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
