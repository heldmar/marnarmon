import ResourceMeter from "./ResourceMeter.jsx";

// One container = one 5-column grid row (DOCKER_MONITOR_SPEC.md §5):
// [ name | RAM meter | CPU meter | Disk meter | View-logs ].
export default function ContainerRow({ container, maxDisk, onViewLogs }) {
  const { name, service, state, mem, cpu, disk } = container;
  return (
    <div className="crow">
      <div className="cname">
        <span className={`state-dot ${state}`} />
        <div style={{ minWidth: 0 }}>
          <div className="n" title={name}>
            {name}
          </div>
          <div className="svc">{service}</div>
        </div>
      </div>

      <ResourceMeter
        kind="RAM"
        usedLabel={mem.usedLabel}
        limitLabel={mem.limitLabel}
        pct={mem.pct}
      />
      <ResourceMeter
        kind="CPU"
        usedLabel={cpu.usedLabel}
        limitLabel={cpu.limitLabel}
        pct={cpu.pct}
      />
      <ResourceMeter
        kind="Disk"
        variant="disk"
        bytes={disk.bytes}
        maxDisk={maxDisk}
        breakdown={disk.breakdown}
      />

      <div className="crow-actions">
        <button
          className="link-btn"
          onClick={onViewLogs}
          aria-label={`View logs for ${name}`}
        >
          <svg
            viewBox="0 0 24 24"
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 5h16" />
            <path d="M4 12h16" />
            <path d="M4 19h10" />
          </svg>
          View logs
        </button>
      </div>
    </div>
  );
}
