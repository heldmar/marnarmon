// Circular progress gauge drawn with plain SVG (no extra deps). Colour shifts
// green -> amber -> red as the value approaches 100.
function colorFor(value) {
  if (value >= 85) return "var(--bad)";
  if (value >= 60) return "var(--warn)";
  return "var(--good)";
}

export default function Gauge({ value = 0, size = 132, stroke = 12, unit = "%" }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  // Leave a 25% gap at the bottom for a "270°" gauge look.
  const arc = 0.75;
  const dash = circumference * arc;
  const offset = dash * (1 - v / 100);
  const color = colorFor(v);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`${v.toFixed(0)}${unit}`}
    >
      <g transform={`rotate(135 ${cx} ${cy})`}>
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--grid)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
        />
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 0.6s ease, stroke 0.3s" }}
        />
      </g>
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="central"
        className="gauge-value"
      >
        {v.toFixed(0)}
        <tspan className="gauge-unit" dx="2">
          {unit}
        </tspan>
      </text>
    </svg>
  );
}
