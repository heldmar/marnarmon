// Fixed vertical icon rail. Hand-drawn stroke SVG icons in the Gauge.jsx style.
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

export default function Sidebar({ section, onSelect, logsEnabled }) {
  const items = [
    { id: "resources", label: "Server Resources", icon: ResourcesIcon },
  ];
  if (logsEnabled) {
    items.push({ id: "logs", label: "Server Logs", icon: LogsIcon });
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
            title={it.label}
            aria-label={it.label}
            aria-current={active ? "page" : undefined}
          >
            {it.icon}
          </button>
        );
      })}
    </nav>
  );
}
