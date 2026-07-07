import { fmtLogTime } from "../format.js";

// Maps the server's severity bucket to a token-coloured pill class.
const SEV_CLASS = {
  error: "bad",
  warning: "warn",
  info: "good",
  debug: "faint",
};

function LogRow({ line, spansDays }) {
  const sev = SEV_CLASS[line.severity] || "good";
  const source = line.source_label || line.source || line.unit;
  return (
    <div className="log-row">
      <span className={`log-sev ${sev}`}>{line.severity_label}</span>
      <span className="log-time">{fmtLogTime(line.ts, spansDays)}</span>
      <span className="log-source" title={line.unit || line.source}>
        {source}
      </span>
      <span className="log-msg">{line.message}</span>
    </div>
  );
}

export default function LogList({ lines, spansDays }) {
  return (
    <div className="log-list">
      {lines.map((l) => (
        <LogRow key={l.cursor} line={l} spansDays={spansDays} />
      ))}
    </div>
  );
}
