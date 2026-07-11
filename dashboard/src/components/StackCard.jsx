import ContainerRow from "./ContainerRow.jsx";

const Caret = (
  <svg
    className="stack-caret"
    viewBox="0 0 24 24"
    width="16"
    height="16"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M6 9l6 6 6-6" />
  </svg>
);

const Cubes = (
  <svg
    className="stack-icon"
    viewBox="0 0 24 24"
    width="18"
    height="18"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M12 2l8 4.5v9L12 20l-8-4.5v-9L12 2z" />
    <path d="M12 20v-9" />
    <path d="M20 6.5L12 11 4 6.5" />
  </svg>
);

function Roll({ k, v }) {
  return (
    <div className="roll">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

// One collapsible card per Compose project (DOCKER_MONITOR_SPEC.md §4).
// Header order: caret, cube icon, name/meta, spacer, .stack-roll, .badge — the
// badge is a SIBLING of .stack-roll so it survives the ≤560px rollup hide.
export default function StackCard({ stack, collapsed, onToggle, maxDisk, onViewLogs }) {
  function onKeyDown(e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onToggle();
    }
  }

  return (
    <div className={`card stack${collapsed ? " collapsed" : ""}`}>
      <div
        className="stack-head"
        role="button"
        tabIndex={0}
        aria-expanded={!collapsed}
        onClick={onToggle}
        onKeyDown={onKeyDown}
      >
        {Caret}
        {Cubes}
        <div style={{ minWidth: 0 }}>
          <div className="stack-name">{stack.name}</div>
          {stack.meta ? <div className="stack-meta">{stack.meta}</div> : null}
        </div>
        <div className="stack-spacer" />
        <div className="stack-roll">
          <Roll k="Memory" v={stack.memLabel} />
          <Roll k="CPU" v={stack.cpuLabel} />
          <Roll k="Disk" v={stack.diskLabel} />
        </div>
        <span className={`badge ${stack.health}`}>{stack.healthLabel}</span>
      </div>

      <div className="stack-body">
        {stack.containers.map((c) => (
          <ContainerRow
            key={c.id || c.name}
            container={c}
            maxDisk={maxDisk}
            onViewLogs={() => onViewLogs(c)}
          />
        ))}
      </div>
    </div>
  );
}
