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
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
  return res.json();
}

export const getCurrent = () => get("/metrics/current");
export const getHealth = () => get("/health");
export const getHistory = (window = "24h") =>
  get(`/metrics/history?window=${encodeURIComponent(window)}`);
