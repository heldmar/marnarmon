import { useState } from "react";
import SegmentedControl from "./SegmentedControl.jsx";

const PRESETS = [
  { label: "15m", value: "15m" },
  { label: "1h", value: "1h" },
  { label: "6h", value: "6h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "Custom", value: "custom" },
];

// datetime-local wants a local "YYYY-MM-DDTHH:mm" string.
function toLocalInput(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

function toEpoch(local) {
  if (!local) return undefined;
  const ms = new Date(local).getTime();
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000);
}

// value: { window } for a preset, or { custom: true, since, until } for a range.
// onChange receives the same shape.
export default function TimeRangeControl({ value, onChange }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const selected = value?.custom ? "custom" : value?.window || "24h";

  function selectPreset(v) {
    if (v !== "custom") {
      onChange({ window: v });
      return;
    }
    // Entering custom mode: seed sensible defaults (last hour) if empty.
    let f = from;
    let t = to;
    if (!f || !t) {
      const now = new Date();
      const hourAgo = new Date(now.getTime() - 60 * 60 * 1000);
      f = f || toLocalInput(hourAgo);
      t = t || toLocalInput(now);
      setFrom(f);
      setTo(t);
    }
    onChange({ custom: true, since: toEpoch(f), until: toEpoch(t) });
  }

  function updateFrom(v) {
    setFrom(v);
    onChange({ custom: true, since: toEpoch(v), until: toEpoch(to) });
  }

  function updateTo(v) {
    setTo(v);
    onChange({ custom: true, since: toEpoch(from), until: toEpoch(v) });
  }

  return (
    <div className="timerange">
      <SegmentedControl
        options={PRESETS}
        value={selected}
        onChange={selectPreset}
        ariaLabel="Time range"
      />
      {selected === "custom" ? (
        <div className="timerange-custom">
          <label className="timerange-input">
            <span className="field-label">From</span>
            <input
              className="input"
              type="datetime-local"
              value={from}
              onChange={(e) => updateFrom(e.target.value)}
            />
          </label>
          <label className="timerange-input">
            <span className="field-label">To</span>
            <input
              className="input"
              type="datetime-local"
              value={to}
              onChange={(e) => updateTo(e.target.value)}
            />
          </label>
        </div>
      ) : null}
    </div>
  );
}
