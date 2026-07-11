import { useMemo, useState } from "react";
import { config } from "../config.js";
import { getDockerOverview, getDockerStacks } from "../api.js";
import { usePolling } from "../hooks/usePolling.js";
import { fmtBytes, fmtRate, fmtClock } from "../format.js";
import Header from "../components/Header.jsx";
import DockerGauges from "../components/DockerGauges.jsx";
import StackCard from "../components/StackCard.jsx";
import ContainerLogs from "../components/ContainerLogs.jsx";

const refreshMs = config.dockerRefreshSeconds * 1000;

// A short lifecycle note appended to the service line so state is never
// colour-only (a11y — see spec §10 / states matrix §8.1).
function stateNote(c) {
  const raw = (c.state_raw || "").toLowerCase();
  if (raw === "restarting") return "restarting";
  if (c.state === "bad") return "stopped";
  if (c.health === "unhealthy") return "unhealthy";
  return null;
}

// Map an API container (snake_case) to the ContainerRow/ResourceMeter view
// model (camelCase, per spec §5/§6). Tolerant of missing nested fields.
function containerVM(c) {
  const mem = c.mem || {};
  const cpu = c.cpu || {};
  const disk = c.disk || {};
  const note = stateNote(c);
  const parts = [c.service, c.image].filter(Boolean).join(" · ");
  const service = note ? `${parts} · ${note}` : parts;

  const volumes = disk.volumes_bytes
    ? ` · volumes ${fmtBytes(disk.volumes_bytes)}`
    : disk.local_volumes
    ? ` · ${disk.local_volumes} volume${disk.local_volumes > 1 ? "s" : ""}`
    : "";

  return {
    id: c.id,
    name: c.name,
    service,
    state: c.state || "ok",
    stack: c.project || "ungrouped",
    image: c.image,
    mem: {
      usedLabel: fmtBytes(mem.used_bytes),
      limitLabel: mem.limit_bytes != null ? fmtBytes(mem.limit_bytes) : null,
      pct: mem.percent != null ? mem.percent : null,
    },
    cpu: {
      usedLabel: `${(cpu.used_cores ?? 0).toFixed(2)} cores`,
      limitLabel: cpu.limit_cores != null ? `${cpu.limit_cores} cores` : null,
      pct: cpu.percent != null ? cpu.percent : null,
    },
    disk: {
      bytes: disk.bytes ?? 0,
      breakdown: `rw ${fmtBytes(disk.rw_bytes ?? 0)}${volumes}`,
    },
  };
}

function stackVM(s) {
  return {
    name: s.name,
    meta: s.meta,
    health: s.health || "ok",
    healthLabel: s.health_label || "Healthy",
    memLabel: fmtBytes(s.mem_used_bytes),
    cpuLabel: (s.cpu_used_cores ?? 0).toFixed(2),
    diskLabel: fmtBytes(s.disk_bytes),
    containers: (s.containers || []).map(containerVM),
  };
}

export default function DockerView({ health, theme, onToggleTheme }) {
  const [live, setLive] = useState(false);
  const [collapsed, setCollapsed] = useState({});
  const [selected, setSelected] = useState(null);

  const overview = usePolling(getDockerOverview, refreshMs, [], { enabled: live });
  const stacksPoll = usePolling(getDockerStacks, refreshMs, [], { enabled: live });

  const ov = overview.data;
  const disabled = overview.errorCode === "docker_disabled";
  const dockerOk = ov ? ov.docker_ok !== false : true;
  const daemonError = ov && ov.docker_ok === false ? ov.error : null;

  const stacks = useMemo(
    () => (stacksPoll.data?.stacks || []).map(stackVM),
    [stacksPoll.data]
  );

  // Largest single-container disk footprint across everything in view — the
  // scale reference passed down to every disk meter (spec §6.2).
  const maxDisk = useMemo(() => {
    let m = 0;
    for (const s of stacks) for (const c of s.containers) m = Math.max(m, c.disk.bytes);
    return m || 1;
  }, [stacks]);

  const containerCount = stacks.reduce((n, s) => n + s.containers.length, 0);
  const stats = ov?.stats || {};

  function refreshAll() {
    overview.refresh();
    stacksPoll.refresh();
    health.refresh();
  }

  if (disabled) {
    return (
      <>
        <Header
          host={health.data?.host}
          health={health.data}
          error={health.error}
          theme={theme}
          onToggleTheme={onToggleTheme}
          onRefresh={refreshAll}
        />
        <div className="center-msg">Docker monitoring isn't enabled on this host.</div>
      </>
    );
  }

  return (
    <>
      <Header
        host={ov?.host || health.data?.host}
        health={health.data}
        error={overview.error || health.error}
        lastUpdated={overview.lastUpdated}
        theme={theme}
        onToggleTheme={onToggleTheme}
        onRefresh={refreshAll}
      />

      <div className="toolbar-row" style={{ justifyContent: "flex-end", marginBottom: 16 }}>
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
        {overview.lastUpdated ? (
          <span className="updated">Updated {fmtClock(overview.lastUpdated)}</span>
        ) : null}
      </div>

      {daemonError ? (
        <div className="banner error">
          Docker daemon unreachable{daemonError ? ": " + daemonError : ""}.
          <div className="muted" style={{ marginTop: 4 }}>
            API: {config.apiBaseUrl}/docker
          </div>
        </div>
      ) : null}

      {!ov && overview.loading ? (
        <div className="center-msg">Loading containers…</div>
      ) : null}

      {ov && dockerOk ? (
        <>
          <div className="section-label">Total consumed by all containers</div>
          <DockerGauges totals={ov.totals} />

          <div className="stats">
            <div className="stat">
              <div className="label">Containers</div>
              <div className="value">
                {stats.running ?? 0}{" "}
                <small style={{ fontSize: 12, color: "var(--text-faint)", fontWeight: 500 }}>
                  running · {stats.stopped ?? 0} stopped
                </small>
              </div>
            </div>
            <div className="stat">
              <div className="label">Stacks</div>
              <div className="value">{stats.stacks ?? stacks.length}</div>
            </div>
            <div className="stat">
              <div className="label">Net I/O</div>
              <div className="value">
                {fmtRate(stats.net_rx_rate)} ↓ · {fmtRate(stats.net_tx_rate)} ↑
              </div>
            </div>
            <div className="stat">
              <div className="label">Restarts (24h)</div>
              <div className="value">{stats.restarts_24h ?? 0}</div>
            </div>
          </div>

          <div className="section-label">Stacks &amp; containers</div>

          <div className="card meters-legend">
            <span className="lg">
              <span className="sw util" />
              RAM / CPU — fills toward each container's limit
            </span>
            <span className="lg">
              <span className="sw disk" />
              Disk — sized against the largest consumer (no limit applies)
            </span>
            <span className="lg">
              <span className="sw nolim" />
              no limit set
            </span>
          </div>

          {stacksPoll.error && !stacks.length ? (
            <div className="banner error">Could not load stacks: {stacksPoll.error}</div>
          ) : !containerCount ? (
            <div className="center-msg">No containers are running on this host.</div>
          ) : (
            stacks.map((s) => (
              <StackCard
                key={s.name}
                stack={s}
                collapsed={!!collapsed[s.name]}
                onToggle={() =>
                  setCollapsed((prev) => ({ ...prev, [s.name]: !prev[s.name] }))
                }
                maxDisk={maxDisk}
                onViewLogs={(c) =>
                  setSelected({ name: c.name, stack: c.stack, image: c.image })
                }
              />
            ))
          )}
        </>
      ) : null}

      <div
        className="muted"
        style={{ marginTop: 24, fontSize: 12, textAlign: "center" }}
      >
        Polling every {config.dockerRefreshSeconds}s · read-only · {config.apiBaseUrl}/docker
      </div>

      <ContainerLogs
        open={!!selected}
        container={selected}
        onClose={() => setSelected(null)}
      />
    </>
  );
}
