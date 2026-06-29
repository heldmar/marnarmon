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

- Gauge panels: CPU, Memory, and one per tracked disk
- Stat strip: net in/out, free memory, uptime
- Time-series charts: CPU %, Memory %, Network in/out, Load average
- Window selector: 1H / 6H / 24H / 7D

## Configuration

All runtime config comes from environment variables (injected into the
container at start, so no rebuild needed to repoint it):

| Variable | Default | Meaning |
|----------|---------|---------|
| `API_BASE_URL` | `/api` | Browser-facing API base. `/api` = same-origin reverse proxy (recommended for public HTTPS). Or a full URL (`http://<lan-ip>:8787`) for direct LAN access. |
| `API_UPSTREAM` | `http://localhost:8787` | Where nginx forwards `/api/` — the host agent **as reached from the container** (host LAN IP). Only used in same-origin mode. |
| `REFRESH_SECONDS` | `300` | Poll interval (5 min) |
| `API_TOKEN` | _(empty)_ | Bearer token, only if the host API has auth enabled |

The browser sends the token directly on each request. In same-origin mode the
token still lands in `/config.js` (client-side), so for a publicly reachable
deployment prefer enforcing access at the reverse proxy (Basic Auth / access
list) rather than relying on the bearer token alone.

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
  -e API_UPSTREAM="http://192.168.4.200:8787" \
  -e REFRESH_SECONDS=300 \
  -e API_TOKEN="" \
  marnarmon-dashboard
```

## Local development

```bash
npm install
# edit public/config.js to point at a running host API, then:
npm run dev        # http://localhost:5173
npm run build      # production bundle into dist/
```

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
