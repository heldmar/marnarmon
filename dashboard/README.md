# MarNarMon Dashboard

A React dashboard, shipped as a Docker container, that visualizes the metrics
served by a MarNarMon host agent. It is a pure API consumer — it needs a running
host agent (in the repo root) but contains none of its code. Open source under
Apache-2.0 (the repo-root [`LICENSE`](../LICENSE)).

## Relationship to the host agent

```
[ host agent ]  --HTTP/JSON-->  [ dashboard ]
  Apache-2.0                       Apache-2.0
```

The only contract between them is the HTTP API in [`../API.md`](../API.md).

## Stack

- React 18 + Vite, **Recharts** (the only external UI dependency)
- Plain-SVG gauges (no component library)
- Dark theme by default, light toggle (persisted in the browser)
- Single host, polling `/metrics/current` + `/metrics/history`
- Runtime-configurable: one built image targets any host

## What it shows

Two sections, switched from a left icon rail:

**Server Resources**
- Gauge panels: CPU, Memory, and one per tracked disk
- Stat strip: net in/out, free memory, uptime
- Time-series charts: CPU %, Memory %, Network in/out, Load average
- Window selector: 1H / 6H / 24H / 7D

**Server Logs** (shown only when the host has it enabled — `features.logs` on
`/health`)
- Keyword search, severity filter (Errors / Warnings / Info / Everything),
  source picker (systemd units + kernel), time range (presets or custom from/to)
- Severity-colored rows, a "Live" auto-refresh toggle, and a manual Refresh

## Configuration

All runtime config comes from environment variables (injected into the
container at start, so no rebuild needed to repoint it):

| Variable | Default | Meaning |
|----------|---------|---------|
| `API_BASE_URL` | `/api` | Browser-facing API base. `/api` = same-origin reverse proxy (recommended for public HTTPS). Or a full URL (`http://<lan-ip>:8787`) for direct LAN access. |
| `API_UPSTREAM` | `http://localhost:8787` | Where nginx forwards `/api/` — the host agent **as reached from the container** (host LAN IP). Only used in same-origin mode. |
| `REFRESH_SECONDS` | `300` | Metrics poll interval (5 min) |
| `LOGS_REFRESH_SECONDS` | `10` | Server Logs "Live" auto-refresh interval. Only relevant when the host has Server Logs enabled. |
| `DOCKER_REFRESH_SECONDS` | `15` | Docker Monitor "Live" auto-refresh interval. Kept modest so each poll's `docker` CLI shell-out stays light on a Pi. Only relevant when the host has Docker Monitor enabled. |
| `API_TOKEN` | _(empty)_ | Bearer token, only if the host API has auth enabled |

`API_TOKEN` must match the host's `api.token`. In the default same-origin proxy
mode the container **injects it into the `/api` Authorization header
server-side**, so it never reaches the browser (`config.js` stays empty); set it
as a stack/environment variable (in Portainer: the stack's *Environment
variables*), never hardcoded in `docker-compose.yml`. In direct mode (full URL
in `API_BASE_URL`) the browser must send it, so it lands in `config.js` — prefer
proxy mode when the dashboard is Internet-reachable, and still enforce real auth
at the reverse proxy (Basic Auth / access list) on top.

### Same-origin proxy (why `/api`)

When the dashboard is served over public HTTPS (e.g. `dashboard.example.net`),
the browser **cannot** call the host's private LAN IP directly: it's
unroutable off the LAN, and an HTTPS page is blocked from fetching a plain
`http://` URL (mixed content). With `API_BASE_URL=/api`, the browser calls
`https://<this-domain>/api/...` and the container's nginx proxies that to
`API_UPSTREAM` (the real host agent), so the API rides the same domain/cert as
the dashboard — no CORS, no mixed content, works from anywhere.

## Run with Docker

```bash
# edit API_BASE_URL (and token) in docker-compose.yml, then:
docker compose up -d --build
# open http://localhost:8080
```

Or build and run the image directly:

```bash
docker build -t marnarmon-dashboard .
docker run -d -p 8080:80 \
  -e API_BASE_URL="/api" \
  -e API_UPSTREAM="http://host.docker.internal:8787" --add-host host.docker.internal:host-gateway \
  -e REFRESH_SECONDS=300 \
  -e LOGS_REFRESH_SECONDS=10 \
  -e DOCKER_REFRESH_SECONDS=15 \
  -e API_TOKEN="" \
  marnarmon-dashboard
```

## Local development

This project uses **pnpm** (via Corepack — `corepack enable` once, then the
version pinned in `package.json`'s `packageManager` field is used automatically).

```bash
pnpm install
# edit public/config.js to point at a running host API, then:
pnpm dev           # http://localhost:5173
pnpm build         # production bundle into dist/
```

### Dependency security policy

`pnpm-workspace.yaml` hardens the supply chain:

- **`minimumReleaseAge: 10080`** — a package version must be public for 7 days
  before pnpm will resolve it, so a compromised release pulled from the registry
  within that window never lands in the lockfile. Applies to `pnpm add` /
  `pnpm update` (not frozen CI/Docker installs).
- **`allowBuilds`** — dependency install/build scripts are blocked by default;
  only explicitly allow-listed packages (currently just `esbuild`, which fetches
  its native binary) may run scripts. Adding a dep that needs a build script
  will hard-fail until you add it here — review before allowing.

## CORS / networking notes

- In same-origin mode (`API_BASE_URL=/api`), the browser calls this domain and
  nginx proxies to `API_UPSTREAM` — no cross-origin request, so CORS doesn't
  apply. `API_UPSTREAM` must be reachable **from inside the container** (host
  LAN IP), not from the browser.
- If you instead set `API_BASE_URL` to a full URL (direct mode), it must be
  reachable **from the user's browser** and, when the page is HTTPS, must also
  be HTTPS — otherwise the browser blocks it as mixed content. The host API
  sends permissive CORS headers for `GET`, so cross-origin `GET` is allowed.

## License

Apache-2.0, same as the host agent — see the repo-root [`LICENSE`](../LICENSE).

## Deploying behind a reverse proxy (e.g. Nginx Proxy Manager)

`docker-compose.yml` joins an `external: true` network named `npm-network` in
addition to its default network. This lets a reverse proxy container (NPM,
Traefik, etc. — anything sharing that Docker network) forward to this
container **by container name** instead of the host IP:

- Forward Hostname/IP: `marnarmon-dashboard`
- Forward Port: `80` (the container's internal nginx port — not the
  host-mapped `8080`; container-to-container traffic on a Docker bridge
  bypasses host port mappings)

If your proxy's shared network has a different name, edit the `networks:`
block in `docker-compose.yml` accordingly. If you don't use a reverse proxy at
all, the `npm-network` block is harmless to leave in place as long as that
network exists on the host (Compose will fail to start otherwise) — remove it
if you have no such network.

`pull_policy: build` is set on the service so that Portainer's "Re-pull image
and redeploy" doesn't fail with `pull access denied` — this image is
build-only and is never pushed to a registry.
