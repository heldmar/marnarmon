import { useState } from "react";
import { config } from "./config.js";
import { getHealth } from "./api.js";
import { usePolling } from "./hooks/usePolling.js";
import { useTheme } from "./hooks/useTheme.js";
import Sidebar from "./components/Sidebar.jsx";
import MetricsView from "./views/MetricsView.jsx";
import LogsView from "./views/LogsView.jsx";

const refreshMs = Math.max(5, config.refreshSeconds) * 1000;

export default function App() {
  const { theme, toggle } = useTheme();
  const [section, setSection] = useState("resources");

  const health = usePolling(getHealth, refreshMs);

  const logsEnabled = !!health.data?.features?.logs;
  const active = section === "logs" && !logsEnabled ? "resources" : section;

  return (
    <div className="shell">
      <Sidebar section={active} onSelect={setSection} logsEnabled={logsEnabled} />
      <div className="app">
        {active === "logs" ? (
          <LogsView health={health} theme={theme} onToggleTheme={toggle} />
        ) : (
          <MetricsView health={health} theme={theme} onToggleTheme={toggle} />
        )}
      </div>
    </div>
  );
}
