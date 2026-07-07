// Formatting helpers (bytes, rates, percent, time).

export function fmtBytes(n) {
  if (n == null || isNaN(n)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let v = Math.abs(n);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  const dp = v >= 100 || i === 0 ? 0 : 1;
  return `${(n < 0 ? -v : v).toFixed(dp)} ${units[i]}`;
}

export function fmtRate(bytesPerSec) {
  if (bytesPerSec == null || isNaN(bytesPerSec)) return "—";
  return `${fmtBytes(bytesPerSec)}/s`;
}

export function fmtPercent(n, dp = 1) {
  if (n == null || isNaN(n)) return "—";
  return `${Number(n).toFixed(dp)}%`;
}

export function fmtUptime(seconds) {
  if (!seconds || seconds < 0) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function fmtClock(date) {
  if (!date) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// X-axis tick formatter for charts: time-of-day for short windows, date for long.
export function makeTimeFormatter(windowMinutes) {
  const longWindow = windowMinutes > 60 * 36; // > ~1.5 days -> show date
  return (tsSeconds) => {
    const d = new Date(tsSeconds * 1000);
    return longWindow
      ? d.toLocaleDateString([], { month: "short", day: "numeric" })
      : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
}

// Log-row timestamp: HH:MM:SS, with a short date prefix when a range spans days.
export function fmtLogTime(tsSeconds, withDate = false) {
  const d = new Date(tsSeconds * 1000);
  const t = d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  if (!withDate) return t;
  const day = d.toLocaleDateString([], { month: "short", day: "numeric" });
  return `${day} ${t}`;
}

export function fmtTooltipTime(tsSeconds) {
  const d = new Date(tsSeconds * 1000);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
