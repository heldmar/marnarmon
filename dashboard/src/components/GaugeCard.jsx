import Gauge from "./Gauge.jsx";

// A titled card wrapping a gauge with an optional footer line.
export default function GaugeCard({ title, value, sub, footer, unavailable = false }) {
  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">{title}</span>
        {sub ? <span className="card-sub">{sub}</span> : null}
      </div>
      <div className="gauge">
        <Gauge value={value} unavailable={unavailable} />
        {footer ? <div className="gauge-foot">{footer}</div> : null}
      </div>
    </div>
  );
}
