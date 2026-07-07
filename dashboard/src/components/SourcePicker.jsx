import { useEffect, useRef, useState } from "react";

const SourceIcon = (
  <svg
    viewBox="0 0 24 24"
    width="15"
    height="15"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M4 6h16" />
    <path d="M7 12h10" />
    <path d="M10 18h4" />
  </svg>
);

// Hand-rolled multi-select. props: sources [{ unit, label }], selected (units[]),
// onChange (units[]). Empty selection means "all sources".
export default function SourcePicker({ sources, selected, onChange }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const q = filter.trim().toLowerCase();
  const shown = q
    ? sources.filter(
        (s) =>
          s.label.toLowerCase().includes(q) || s.unit.toLowerCase().includes(q)
      )
    : sources;

  function toggle(unit) {
    onChange(
      selected.includes(unit)
        ? selected.filter((u) => u !== unit)
        : [...selected, unit]
    );
  }

  const count = selected.length;

  return (
    <div className="picker" ref={ref}>
      <button
        className="btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Filter by source"
        title="Filter by source"
      >
        {SourceIcon}
        Sources{count ? ` · ${count}` : ""}
      </button>
      {open ? (
        <div className="picker-pop card" role="dialog" aria-label="Choose sources">
          <input
            className="input"
            type="search"
            placeholder="Filter sources…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            autoFocus
          />
          <div className="picker-list">
            {shown.length ? (
              shown.map((s) => (
                <label key={s.unit} className="picker-item">
                  <input
                    type="checkbox"
                    checked={selected.includes(s.unit)}
                    onChange={() => toggle(s.unit)}
                  />
                  <span title={s.unit}>{s.label}</span>
                </label>
              ))
            ) : (
              <div className="muted picker-empty">No matching sources</div>
            )}
          </div>
          {count ? (
            <button className="btn picker-clear" onClick={() => onChange([])}>
              Clear selection
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
