// Thin client for the MarNarMon host API. See ../../API.md for the contract.
import { config } from "./config.js";

function headers() {
  const h = { Accept: "application/json" };
  if (config.apiToken) h["Authorization"] = `Bearer ${config.apiToken}`;
  return h;
}

async function get(path) {
  let res;
  try {
    res = await fetch(`${config.apiBaseUrl}${path}`, { headers: headers() });
  } catch (e) {
    throw new Error(
      `Cannot reach API at ${config.apiBaseUrl} (network/CORS). ${e.message || e}`
    );
  }
  if (res.status === 401) throw new Error("Unauthorized — check API token.");
  if (!res.ok) {
    let code;
    try {
      const body = await res.json();
      if (body && body.code) code = body.code;
    } catch {
      /* body wasn't JSON — ignore */
    }
    const err = new Error(`API ${res.status} ${res.statusText}`);
    if (code) err.code = code;
    throw err;
  }
  return res.json();
}

export const getCurrent = () => get("/metrics/current");
export const getHealth = () => get("/health");
export const getHistory = (window = "24h") =>
  get(`/metrics/history?window=${encodeURIComponent(window)}`);

export const getLogSources = () => get("/logs/sources");

export const getDockerOverview = () => get("/docker/overview");
export const getDockerStacks = () => get("/docker/stacks");

export function getDockerLogs(container, opts = {}) {
  const qs = new URLSearchParams({ container });
  if (opts.tail != null) qs.append("tail", opts.tail);
  if (opts.since != null && opts.since !== "") qs.append("since", opts.since);
  return get(`/docker/logs?${qs.toString()}`);
}

export function getLogs(params = {}) {
  const { units, ...rest } = params;
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(rest)) {
    if (value == null || value === "") continue;
    qs.append(key, value);
  }
  for (const unit of units || []) {
    if (unit) qs.append("unit", unit);
  }
  const s = qs.toString();
  return get(`/logs${s ? `?${s}` : ""}`);
}
