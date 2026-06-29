# MarNarMon Dashboard — project guide

Context for Claude Code / contributors. This is the dashboard half of MarNarMon,
**open source (Apache-2.0)** and part of the same repo as the host agent (the
top-level directory). Licensing is the repo-root `LICENSE`.

## What this is

A React dashboard, shipped as a Docker container, that visualizes metrics from a
MarNarMon host agent. It is a **pure API consumer** — it needs a running host
agent but contains none of its code. The only contract is the host's HTTP API,
documented in `../API.md` (v1).

## Stack & layout

- React 18 + Vite, **Recharts is the only external UI dependency**. Gauges are
  hand-drawn SVG — do not add a component library.
- **Package manager is pnpm** (not npm), via Corepack, version pinned in
  `package.json` `packageManager`. Lockfile is `pnpm-lock.yaml`; there is no
  `package-lock.json`. Settings + supply-chain policy live in
  `pnpm-workspace.yaml`.
- `src/` — `App.jsx` (orchestration), `api.js`, `config.js`, `format.js`,
  `hooks/` (`usePolling`, `useTheme`), `components/` (`Gauge`, `GaugeCard`,
  `TimeSeriesChart`, `Header`, `WindowSelector`).
- `Dockerfile` (multi-stage node→nginx), `nginx.conf`, `docker-entrypoint.sh`,
  `docker-compose.yml`, `.env.example`, `pnpm-workspace.yaml`.

## Design decisions (respect these)

- **Dark theme by default**, light toggle persisted in `localStorage`.
- **Single host** (multi-host is a candidate future feature).
- **pnpm, hardened for supply-chain safety** (migrated from npm). Policy in
  `pnpm-workspace.yaml`: `minimumReleaseAge: 10080` (won't resolve a version
  until it's been public 7 days, so a yanked-malicious release never lands) and
  `allowBuilds` (install/build scripts blocked unless allow-listed; only
  `esbuild` is permitted). Don't loosen these or switch back to npm without a
  reason. The Docker build uses `pnpm install --frozen-lockfile`.
- **Runtime config, NOT build-time.** The app reads
  `window.__MARNARMON_CONFIG__` from `/config.js`. In Docker, the entrypoint in
  `/docker-entrypoint.d/` rewrites `config.js` from env vars
  (`API_BASE_URL`, `REFRESH_SECONDS`, `API_TOKEN`) at container start, so one
  built image targets any host. Keep this — don't bake env at build time.
- **Same-origin API proxy is the default.** `API_BASE_URL` defaults to `/api`;
  the entrypoint also writes `/etc/nginx/marnarmon-api-proxy.conf` (a
  `location /api/` block, included by `nginx.conf`) that proxies to
  `API_UPSTREAM`. This is what makes the dashboard work over public HTTPS: the
  browser only ever talks to its own origin, dodging mixed-content + private-IP
  + CORS. Direct mode (full URL in `API_BASE_URL`, no proxy) still works for
  LAN-only use. Don't revert the default to a hardcoded host URL.
- **The browser sends the bearer token** on each request, and in same-origin
  mode the token is still visible in client-side `/config.js`. For a publicly
  reachable deployment, enforce real auth at the reverse proxy (Basic Auth /
  access list), not the bearer token alone.

## Gotchas

- In same-origin mode (default), `API_UPSTREAM` must be reachable **from inside
  the container** (host LAN IP), while the browser only hits `/api` on this
  domain. In direct mode (full URL in `API_BASE_URL`), that URL must be reachable
  **from the user's browser** — `localhost` will not work, and an HTTP URL on an
  HTTPS page is blocked as mixed content.
- Tolerate unknown extra fields from the API and don't assume a fixed disk count
  (forward-compatible with API v1).
- Don't run `pnpm install` in a Cowork-mounted folder you need to clean later —
  the sandbox can't delete the `node_modules` it creates. Docker's multi-stage
  build installs deps inside the image instead. To touch the lockfile without
  installing, use `pnpm install --lockfile-only` or `pnpm import` (no
  `node_modules`).
- **pnpm 11 supply-chain policy lives in `pnpm-workspace.yaml`** (`allowBuilds`,
  `minimumReleaseAge`) — see Design decisions. Two pnpm-11 gotchas: the old
  `onlyBuiltDependencies` key was **removed** in favor of the `allowBuilds`
  map (`pkg: true`), and `strictDepBuilds` defaults to `true` so an unreviewed
  build script is a hard `ERR_PNPM_IGNORED_BUILDS` error, not a warning.
- **Reverse-proxying by container name (NPM, Traefik, etc.) requires this
  container to share a Docker network with the proxy.** That's why
  `docker-compose.yml` joins `npm-network` (`external: true`) — without it the
  proxy can't resolve the container name at all (symptom: proxy's own
  fallback/default page is served instead, or a TLS handshake error like
  Cloudflare `525` if HTTPS-only). Once on the shared network, forward to the
  container's **internal** port (`80`), not the host-mapped port (`8080`).
- **`pull_policy: build` is required for Portainer "Repository" stacks.**
  Without it, Portainer's redeploy/update flow runs `docker compose pull`
  first and fails with `pull access denied for marnarmon-dashboard` — the
  image is build-only and never pushed to a registry.

## Dev / build

Uses **pnpm** via Corepack (`corepack enable` once).

```bash
pnpm install
# edit public/config.js to point at a running host API
pnpm dev         # http://localhost:5173
pnpm build       # -> dist/
# Docker: edit API_BASE_URL in docker-compose.yml, then:
docker compose up -d --build   # http://localhost:8080
```
