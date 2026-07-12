import GaugeCard from "./GaugeCard.jsx";
import { fmtBytes } from "../format.js";

// Three aggregate host-pressure gauges (DOCKER_MONITOR_SPEC.md §3.1). These use
// the standard util colour scale (good/warn/bad at 60/85) because at the host
// level there IS a total to fill toward — unlike the per-container disk meter.
export default function DockerGauges({ totals }) {
  const cpu = totals?.cpu || {};
  const mem = totals?.mem || {};
  const disk = totals?.disk || {};

  // Host memory accounting is off (e.g. Raspberry Pi kernel with the memory
  // cgroup disabled): docker reports 0 B for every container, so plot "n/a"
  // instead of a misleading 0%.
  const memUnavailable = mem.available === false;

  return (
    <div className="grid gauges">
      <GaugeCard
        title="CPU"
        value={cpu.percent}
        footer={
          <span>
            <strong>{(cpu.used_cores ?? 0).toFixed(2)}</strong> of{" "}
            {cpu.host_cores ?? "—"} cores · {Math.round(cpu.percent ?? 0)}% of host
          </span>
        }
      />
      <GaugeCard
        title="Memory"
        value={mem.percent}
        unavailable={memUnavailable}
        footer={
          memUnavailable ? (
            <span>Unavailable — host memory cgroup disabled</span>
          ) : (
            <span>
              <strong>{fmtBytes(mem.used_bytes)}</strong> of{" "}
              {fmtBytes(mem.total_bytes)} used by containers
            </span>
          )
        }
      />
      <GaugeCard
        title="Disk"
        value={disk.percent}
        footer={
          <span>
            <strong>{fmtBytes(disk.used_bytes)}</strong> · images{" "}
            {fmtBytes(disk.images_bytes)} · volumes {fmtBytes(disk.volumes_bytes)}{" "}
            · containers {fmtBytes(disk.containers_bytes)}
          </span>
        }
      />
    </div>
  );
}
