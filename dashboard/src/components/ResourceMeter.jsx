import { colorFor } from "./Gauge.jsx";
import { fmtBytes } from "../format.js";

// A single meter with two semantics (DOCKER_MONITOR_SPEC.md §6):
//   variant="util" (RAM/CPU) — coloured by colorFor():
//     • limit set (pct != null) ⇒ used-vs-limit, "{used} / {limit}".
//     • no limit (pct == null) but hostPct known ⇒ share-of-host fill,
//       "{used} · {n}% of host".
//     • unavailable (RAM when the host memory cgroup is off) ⇒ hatched track,
//       "unavailable" — never a misleading 0.
//     • no limit and no host reference ⇒ hatched, "{used} / no limit".
//   variant="disk" — informational footprint; ALWAYS blue (--accent), scaled
//     against maxDisk (the largest container footprint in view). Never coloured
//     by threshold — a footprint has no limit to fill toward.
export default function ResourceMeter({
  kind,
  variant = "util",
  usedLabel,
  limitLabel = null,
  pct = null,
  hostPct = null,
  unavailable = false,
  bytes,
  maxDisk,
  breakdown,
}) {
  if (variant === "disk") {
    const width = maxDisk ? Math.max(2, Math.min(100, Math.round((bytes / maxDisk) * 100))) : 2;
    const label = fmtBytes(bytes);
    return (
      <div>
        <div className="meter-label">
          <span className="mk">{kind}</span>
          <span className="mv">
            {label}
            {breakdown ? (
              <span title={breakdown} aria-label={breakdown} style={{ cursor: "help" }}>
                {" "}
                ⓘ
              </span>
            ) : null}
          </span>
        </div>
        <div
          className="meter disk"
          role="meter"
          aria-label={`${kind} ${label}`}
        >
          <span style={{ width: `${width}%` }} />
        </div>
      </div>
    );
  }

  // util mode — pick the fill semantics (see the header comment).
  const hasLimit = pct != null;
  const hasHostShare = !hasLimit && !unavailable && hostPct != null;
  // Hatched empty track when there's nothing meaningful to fill toward.
  const hatched = unavailable || (!hasLimit && !hasHostShare);
  const fillPct = hasLimit ? pct : hasHostShare ? hostPct : 0;
  const clamped = hatched ? 100 : Math.max(2, Math.min(100, Math.round(fillPct)));

  let value;
  let aria;
  if (unavailable) {
    value = <em>unavailable</em>;
    aria = `${kind} unavailable`;
  } else if (hasLimit) {
    value = <> / {limitLabel}</>;
    aria = `${kind} ${usedLabel} of ${limitLabel}, ${Math.round(pct)}%`;
  } else if (hasHostShare) {
    value = (
      <>
        {" "}
        · <em>{Math.round(hostPct)}% of host</em>
      </>
    );
    aria = `${kind} ${usedLabel}, ${Math.round(hostPct)}% of host, no limit set`;
  } else {
    value = (
      <>
        {" "}
        / <em>no limit</em>
      </>
    );
    aria = `${kind} ${usedLabel}, no limit set`;
  }

  return (
    <div>
      <div className="meter-label">
        <span className="mk">{kind}</span>
        <span className="mv">
          {unavailable ? null : usedLabel}
          {value}
        </span>
      </div>
      <div
        className={`meter${hatched ? " nolimit" : ""}`}
        role="meter"
        aria-label={aria}
      >
        <span
          style={{
            width: `${clamped}%`,
            background: hatched ? "transparent" : colorFor(fillPct),
          }}
        />
      </div>
    </div>
  );
}
