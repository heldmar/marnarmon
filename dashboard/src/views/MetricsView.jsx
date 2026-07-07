import { useMemo, useState } from "react";
import { config } from "../config.js";
import { getCurrent, getHistory } from "../api.js";
import { usePolling } from "../hooks/usePolling.js";
import {
  fmtBytes,
  fmtRate,
  fmtUptime,
  makeTimeFormatter,
} from "../format.js";
import Header from "../components/Header.jsx";
import GaugeCard from "../components/GaugeCard.jsx";
import TimeSeriesChart from "../components/TimeSeriesChart.jsx";
import WindowSelector from "../components/WindowSelector.jsx";

const WINDOW_MINUTES = { "1h": 60, "6h": 360, "24h": 1440, "7d": 10080 };
const refreshMs = Math.max(5, config.refreshSeconds) * 1000;

export default function MetricsView({ health, theme, onToggleTheme }) {
  const [win, setWin] = useState("24h");

  const current = usePolling(getCurrent, refreshMs);
  const history = usePolling(() => getHistory(win), refreshMs, [win]);

  const cur = current.data;
  const hist = history.data;
  const winMinutes = WINDOW_MINUTES[win] || 1440;
  const xFmt = useMemo(() => makeTimeFormatter(winMinutes), [winMinutes]);

  const disks = cur?.disks || [];
  const snapshots = hist?.snapshots || [];

  return (
    <>
      <Header
        host={cur?.host || health.data?.host}
        health={health.data}
        error={current.error || health.error}
        lastUpdated={current.lastUpdated}
        theme={theme}
        onToggleTheme={onToggleTheme}
        onRefresh={() => {
          current.refresh();
          history.refresh();
          health.refresh();
        }}
      />

      {current.error ? (
        <div className="banner error">
          {current.error}
          <div className="muted" style={{ marginTop: 4 }}>
            API: {config.apiBaseUrl}
          </div>
        </div>
      ) : null}

      {!cur && current.loading ? (
        <div className="center-msg">Loading metrics…</div>
      ) : null}

      {cur ? (
        <>
          {/* Gauges: CPU, RAM, each disk */}
          <div className="grid gauges">
            <GaugeCard
              title="CPU"
              value={cur.cpu_percent}
              footer={
                <span>
                  Load <strong>{(cur.load1 ?? 0).toFixed(2)}</strong> ·{" "}
                  {(cur.load5 ?? 0).toFixed(2)} · {(cur.load15 ?? 0).toFixed(2)}
                </span>
              }
            />
            <GaugeCard
              title="Memory"
              value={cur.mem_percent}
              footer={
                <span>
                  <strong>{fmtBytes(cur.mem_used_kb * 1024)}</strong> of{" "}
                  {fmtBytes(cur.mem_total_kb * 1024)}
                </span>
              }
            />
            {disks.map((d) => (
              <GaugeCard
                key={d.mount}
                title={`Disk ${d.mount}`}
                value={d.percent}
                footer={
                  <span>
                    <strong>{fmtBytes(d.used_bytes)}</strong> of{" "}
                    {fmtBytes(d.total_bytes)}
                    <br />
                    {fmtBytes(d.free_bytes)} free
                  </span>
                }
              />
            ))}
          </div>

          {/* Quick stats */}
          <div className="stats">
            <div className="stat">
              <div className="label">Net In</div>
              <div className="value">{fmtRate(cur.net_rx_rate)}</div>
            </div>
            <div className="stat">
              <div className="label">Net Out</div>
              <div className="value">{fmtRate(cur.net_tx_rate)}</div>
            </div>
            <div className="stat">
              <div className="label">Memory Free</div>
              <div className="value">{fmtBytes(cur.mem_available_kb * 1024)}</div>
            </div>
            <div className="stat">
              <div className="label">Uptime</div>
              <div className="value">{fmtUptime(cur.uptime_seconds)}</div>
            </div>
          </div>
        </>
      ) : null}

      {/* History window control */}
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginBottom: 12,
        }}
      >
        <WindowSelector value={win} onChange={setWin} />
      </div>

      {history.error && !snapshots.length ? (
        <div className="banner error">History unavailable: {history.error}</div>
      ) : null}

      {/* Time-series charts */}
      <div className="grid charts">
        <TimeSeriesChart
          title="CPU usage"
          sub="%"
          data={snapshots}
          series={[{ key: "cpu_percent", name: "CPU", color: "var(--accent)" }]}
          yFormatter={(v) => `${Math.round(v)}%`}
          xFormatter={xFmt}
        />
        <TimeSeriesChart
          title="Memory usage"
          sub="%"
          data={snapshots}
          series={[{ key: "mem_percent", name: "Memory", color: "#a78bfa" }]}
          yFormatter={(v) => `${Math.round(v)}%`}
          xFormatter={xFmt}
        />
        <TimeSeriesChart
          title="Network throughput"
          sub="in / out"
          data={snapshots}
          series={[
            { key: "net_rx_rate", name: "In", color: "var(--good)" },
            { key: "net_tx_rate", name: "Out", color: "var(--warn)" },
          ]}
          yFormatter={(v) => fmtRate(v)}
          xFormatter={xFmt}
        />
        <TimeSeriesChart
          title="Load average (1m)"
          data={snapshots}
          series={[{ key: "load1", name: "Load 1m", color: "#f76d6d" }]}
          yFormatter={(v) => Number(v).toFixed(2)}
          xFormatter={xFmt}
        />
      </div>

      <div
        className="muted"
        style={{ marginTop: 24, fontSize: 12, textAlign: "center" }}
      >
        Polling every {config.refreshSeconds}s · {config.apiBaseUrl}
      </div>
    </>
  );
}
