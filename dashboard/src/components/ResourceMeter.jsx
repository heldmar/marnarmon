import { colorFor } from "./Gauge.jsx";
import { fmtBytes } from "../format.js";

// A single meter with two semantics (DOCKER_MONITOR_SPEC.md §6):
//   variant="util" (RAM/CPU) — used-vs-limit; fill coloured by colorFor(pct).
//     pct === null  ⇒ no limit set: hatched empty track, "{used} / no limit".
//   variant="disk" — informational footprint; ALWAYS blue (--accent), scaled
//     against maxDisk (the largest container footprint in view). Never coloured
//     by threshold — a footprint has no limit to fill toward.
export default function ResourceMeter({
  kind,
  variant = "util",
  usedLabel,
  limitLabel = null,
  pct = null,
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

  // util mode
  const noLimit = pct == null;
  const clamped = noLimit ? 100 : Math.max(2, Math.min(100, Math.round(pct)));
  return (
    <div>
      <div className="meter-label">
        <span className="mk">{kind}</span>
        <span className="mv">
          {usedLabel}
          {noLimit ? (
            <>
              {" "}
              / <em>no limit</em>
            </>
          ) : (
            <> / {limitLabel}</>
          )}
        </span>
      </div>
      <div
        className={`meter${noLimit ? " nolimit" : ""}`}
        role="meter"
        aria-label={
          noLimit
            ? `${kind} ${usedLabel}, no limit set`
            : `${kind} ${usedLabel} of ${limitLabel}, ${Math.round(pct)}%`
        }
      >
        <span
          style={{
            width: `${clamped}%`,
            background: noLimit ? "transparent" : colorFor(pct),
          }}
        />
      </div>
    </div>
  );
}
