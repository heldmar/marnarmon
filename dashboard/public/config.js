// MarNarMon runtime configuration (development defaults).
//
// In the Docker image this file is OVERWRITTEN at container start by
// docker-entrypoint.sh using the API_BASE_URL / REFRESH_SECONDS / API_TOKEN
// environment variables, so a single built image can point at any host without
// rebuilding. Edit the values below for local `npm run dev`.
window.__MARNARMON_CONFIG__ = {
  API_BASE_URL: "http://localhost:8787",
  REFRESH_SECONDS: 300,
  API_TOKEN: "",
};
