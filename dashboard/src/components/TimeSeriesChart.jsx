import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtTooltipTime } from "../format.js";

// Generic time-series area chart.
// props:
//   data: [{ ts, <key>: number, ... }]
//   series: [{ key, name, color }]
//   yFormatter: (v) => string
//   xFormatter: (ts) => string
export default function TimeSeriesChart({
  title,
  data = [],
  series = [],
  yFormatter = (v) => v,
  xFormatter = (v) => v,
  sub,
}) {
  const hasData = data && data.length > 0;
  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">{title}</span>
        {sub ? <span className="card-sub">{sub}</span> : null}
      </div>
      {!hasData ? (
        <div className="center-msg" style={{ padding: "48px 0" }}>
          No data in this window yet.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              {series.map((s) => (
                <linearGradient
                  key={s.key}
                  id={`grad-${s.key}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor={s.color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={s.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="ts"
              tickFormatter={xFormatter}
              tick={{ fontSize: 11, fill: "var(--text-faint)" }}
              stroke="var(--border)"
              minTickGap={40}
            />
            <YAxis
              tickFormatter={yFormatter}
              tick={{ fontSize: 11, fill: "var(--text-faint)" }}
              stroke="var(--border)"
              width={52}
            />
            <Tooltip
              contentStyle={{
                background: "var(--bg-elev)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                color: "var(--text)",
                fontSize: 12,
              }}
              labelFormatter={(ts) => fmtTooltipTime(ts)}
              formatter={(value, name) => [yFormatter(value), name]}
            />
            {series.length > 1 ? (
              <Legend
                wrapperStyle={{ fontSize: 12, color: "var(--text-dim)" }}
                iconType="plainline"
              />
            ) : null}
            {series.map((s) => (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.name}
                stroke={s.color}
                strokeWidth={2}
                fill={`url(#grad-${s.key})`}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
