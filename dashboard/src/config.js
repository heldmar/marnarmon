// Resolve runtime config from window.__MARNARMON_CONFIG__ (injected by
// /config.js), falling back to Vite build-time env for flexibility, then
// sensible defaults.
const rt = (typeof window !== "undefined" && window.__MARNARMON_CONFIG__) || {};

export const config = {
  apiBaseUrl: (
    rt.API_BASE_URL ||
    import.meta.env.VITE_API_BASE_URL ||
    "http://localhost:8787"
  ).replace(/\/+$/, ""),
  refreshSeconds: Number(
    rt.REFRESH_SECONDS || import.meta.env.VITE_REFRESH_SECONDS || 300
  ),
  logsRefreshSeconds: Number(
    rt.LOGS_REFRESH_SECONDS || import.meta.env.VITE_LOGS_REFRESH_SECONDS || 10
  ),
  dockerRefreshSeconds: Number(
    rt.DOCKER_REFRESH_SECONDS || import.meta.env.VITE_DOCKER_REFRESH_SECONDS || 15
  ),
  apiToken: rt.API_TOKEN || import.meta.env.VITE_API_TOKEN || "",
};
