# MarNarMon API contract (v1)

This is the stable boundary between the **host agent** and the **dashboard**
(both in this repo, under `dashboard/`). Both sides build against this spec.
Treat it as versioned: additive changes are fine; breaking changes get a new
major version and a new path prefix.

- Base URL: `http://<host>:<port>` (default port `8787`)
- All responses are JSON.
- **Auth:** if a bearer token is configured (`api.token` in `config.yml`), every
  endpoint except `/` requires `Authorization: Bearer <token>`. Otherwise no
  auth is required. **Set a token whenever the API is reachable beyond
  localhost** — it is the only thing guarding metrics and, if enabled, the
  system journal.
- **CORS:** `GET` from the origins in `api.allowed_origins` (default `["*"]`).
  Restrict it to the dashboard origin(s) on untrusted networks.
- **Times:** all timestamps are Unix epoch **seconds** (integer, UTC).
- **Bytes:** all sizes are bytes. Network rates are **bytes per second**,
  averaged over the interval since the previous sample.

---

## `GET /`

Open (no auth). Service banner. `features` advertises optional capabilities the
dashboard adapts to (see `/health`).

```json
{
  "service": "marnarmon",
  "version": "0.1.0",
  "host": "pi-server",
  "features": { "logs": false, "docker": false }
}
```

## `GET /health`

Liveness and freshness. `status` is `"ok"` when the most recent sample is newer
than 3× the collection interval, else `"stale"`.

```json
{
  "status": "ok",
  "host": "pi-server",
  "last_sample_ts": 1782331556,
  "last_sample_age_seconds": 12,
  "interval_minutes": 5,
  "features": { "logs": false, "docker": false }
}
```

`503` is never returned here; a brand-new install with no samples yet returns
`status: "stale"` with `last_sample_ts: null`.

**`features`** is a capability map. `features.logs` is `true` when Server Logs
is enabled on this host (`logs.enabled` in config); `features.docker` is `true`
when Docker Monitor is enabled (`docker.enabled` in config). The dashboard reads
each flag to decide whether to show that section at all — when a flag is
`false`, its endpoints below return `503` and the UI hides the section entirely.

## `GET /metrics/current`

Latest snapshot. Returns `503` if no sample has been collected yet.

```json
{
  "ts": 1782331556,
  "cpu_percent": 0.49,
  "cpu_total": 6326246,
  "cpu_idle": 6322872,
  "mem_total_kb": 3997920,
  "mem_available_kb": 3621352,
  "mem_used_kb": 376568,
  "mem_percent": 9.42,
  "net_rx_bytes": 10485760,
  "net_tx_bytes": 2097152,
  "net_rx_rate": 1024.0,
  "net_tx_rate": 256.0,
  "load1": 0.14,
  "load5": 0.03,
  "load15": 0.01,
  "uptime_seconds": 15823.58,
  "disks": [
    {
      "mount": "/",
      "total_bytes": 10222313472,
      "used_bytes": 5491965952,
      "free_bytes": 4713570304,
      "percent": 53.81
    }
  ],
  "host": "pi-server"
}
```

Field notes:

- `cpu_total` / `cpu_idle` are cumulative jiffies (internal; the dashboard uses
  `cpu_percent`).
- `net_rx_bytes` / `net_tx_bytes` are cumulative interface counters; the
  dashboard uses `net_rx_rate` / `net_tx_rate` for charts.
- `disks` has one object per tracked mount point.

## `GET /metrics/history`

Time series for charts. Window selection:

- `?window=30m | 24h | 7d` — convenient units, **or**
- `?minutes=N` — explicit (takes precedence over `window`)
- neither → server default (`api.default_history_minutes`, default 1440 = 24h)

```
GET /metrics/history?window=24h
```

```json
{
  "snapshots": [
    {
      "ts": 1782331556,
      "cpu_percent": 0.49,
      "mem_percent": 9.42,
      "net_rx_rate": 1024.0,
      "net_tx_rate": 256.0,
      "load1": 0.14,
      "load5": 0.03,
      "load15": 0.01
    }
  ],
  "disks": {
    "/": [
      { "ts": 1782331556, "used_bytes": 5491965952, "total_bytes": 10222313472, "percent": 53.81 }
    ]
  },
  "host": "pi-server",
  "window_minutes": 1440
}
```

- `snapshots` is ordered oldest → newest.
- `disks` is keyed by mount point, each an oldest → newest series.
- An invalid `window` string returns `400`.

---

## Server Logs (systemd journal)

Opt-in, off by default. When `logs.enabled` is `false`, both endpoints below
return **`503`** with a machine-readable code and no other body:

```json
{ "code": "logs_disabled", "message": "Server Logs is not enabled on this host." }
```

Clients should key off `features.logs` from `/health` rather than probing these.
Both endpoints are read-only (`GET`) and honor the same bearer-token auth.

### `GET /logs/sources`

The selectable log sources: every systemd unit that has ever logged (transient
`*.scope` / `*.mount` / `*.slice` / `*.socket` / `*.target` / `*.device` noise
filtered out) plus a synthetic `"kernel"` source. `unit` is the raw value to
send back as a `?unit=` filter; `label` is a friendly display name. Cached
server-side for ~60s.

```json
{
  "host": "pi-server",
  "sources": [
    { "unit": "kernel", "label": "Kernel" },
    { "unit": "nginx.service", "label": "Nginx" },
    { "unit": "ssh.service", "label": "Ssh" }
  ]
}
```

### `GET /logs`

Filtered journal lines, **newest first**. All filters are optional and combine
(AND across different filters; multiple `unit` values OR together).

| Param | Meaning |
|-------|---------|
| `q` | Keyword — matched as a **literal substring**, case-insensitive (no regex knowledge needed). |
| `severity` | `errors` \| `warnings` \| `info` \| `all` (default `all`). **Cumulative**: `warnings` includes errors, `info` includes warnings+errors, `all` adds debug. |
| `unit` | Source filter, repeatable (`?unit=nginx.service&unit=kernel`). Values come from `/logs/sources`. |
| `window` | `30m` \| `24h` \| `7d` — look-back from now. |
| `since` / `until` | Epoch **seconds** for a custom absolute range (takes precedence over `window`). |
| `limit` | Max lines (capped server-side at `logs.max_lines`). |
| `after_cursor` | Return only lines after this cursor (live catch-up). |
| `exclude_cursor` | Drop this one cursor from the result (boundary de-dup for "load older"). |

Neither `window` nor `since`/`until` → server default
(`logs.default_window_minutes`, default 60).

```
GET /logs?severity=errors&q=disk&window=24h&limit=100
```

```json
{
  "host": "pi-server",
  "lines": [
    {
      "ts": 1782331556,
      "cursor": "s=abc;i=1f4;...",
      "priority": 3,
      "severity": "error",
      "severity_label": "Error",
      "unit": "nginx.service",
      "source": "nginx.service",
      "source_label": "Nginx",
      "identifier": "nginx",
      "pid": "812",
      "hostname": "pi-server",
      "message": "connect() failed: No space left on device"
    }
  ],
  "count": 1,
  "truncated": false,
  "window_minutes": 1440
}
```

- `priority` is the raw syslog level 0–7; `severity` is a coarse bucket
  (`error` / `warning` / `info` / `debug`) for row coloring; `severity_label` is
  the human name of the exact level.
- `source` is the unit name, or `"kernel"`, or the syslog identifier when a line
  has no unit; `source_label` is its friendly form.
- `truncated` is `true` when the result hit `limit` (more lines may exist).
- `window_minutes` is `null` when a custom `since`/`until` range was used.
- A journalctl failure (bad filter, timeout, missing binary) returns `502`.

---

## Docker Monitor (container & stack resources + live logs)

Opt-in, off by default. When `docker.enabled` is `false`, all three endpoints
below return **`503`** with a machine-readable code and no other body:

```json
{ "code": "docker_disabled", "message": "Docker Monitor is not enabled on this host." }
```

Clients should key off `features.docker` from `/health` rather than probing
these. All three are read-only (`GET`) and honor the same bearer-token auth.

**Daemon reachability is a data state, not an HTTP error.** `/docker/overview`
and `/docker/stacks` return **`200`** even when the docker daemon is
unreachable (missing binary, permission denied, timeout): the body carries
`docker_ok: false` and an `error` string, with the payload fields nulled/emptied.
The dashboard renders this as a banner, so a down daemon is never a `5xx`.

All values are read **live per request** — no docker history is stored (mirrors
Server Logs). Every size is bytes; CPU is expressed as cores (`100%` of a
`docker stats` CPU reading equals one full core).

### `GET /docker/overview`

Aggregate host-pressure gauges (percent of host cores / RAM / disk) plus
quick-stat counts across every container. Hot-path cost is three docker
subprocesses (`ps`, `stats`, and a cheap summary `system df`); the `ps` + `stats`
snapshot is shared with `/docker/stacks` (see below). The 24h restart count adds
a `docker events` call only when its cache (`docker.events_cache_seconds`) has
expired.

```json
{
  "host": "pi-server",
  "docker_ok": true,
  "error": null,
  "totals": {
    "cpu":  { "percent": 12.5, "used_cores": 0.5, "host_cores": 4 },
    "mem":  { "percent": 41.2, "used_bytes": 1648361472, "total_bytes": 3997925376 },
    "disk": {
      "percent": 18.4,
      "used_bytes": 1932735283,
      "total_bytes": 10485760000,
      "images_bytes": 1288490188,
      "volumes_bytes": 536870912,
      "containers_bytes": 107374182
    }
  },
  "stats": {
    "running": 6,
    "stopped": 1,
    "total": 7,
    "stacks": 3,
    "unhealthy": 0,
    "net_rx_rate": 1258291,
    "net_tx_rate": 838860,
    "restarts_24h": 0
  }
}
```

Field notes:

- `totals.cpu` / `totals.mem` / `totals.disk` are **host pressure**: percentages
  are computed against the host's core count, `/proc/meminfo` total, and the
  size of the filesystem backing docker (`statvfs` of `/`).
- `totals.disk` is the sum of the docker `images` / `volumes` / `containers`
  buckets from the summary `system df` (each also surfaced individually).
- `stats.net_rx_rate` / `stats.net_tx_rate` are a real **bytes/sec rate**, derived
  as the in-memory delta between successive `docker stats` snapshots (docker's
  NetIO is cumulative-since-start, so the API differences consecutive polls the
  same way the host collector differences SQLite samples). The first poll after
  start — and any container that just restarted (its counter reset) — contributes
  `0` for that interval rather than a bogus spike; no extra subprocess is needed.
- `stats.restarts_24h` is a **true count** of container restart events in the last
  24 hours, from a `docker events --since 24h` window. That query is cached
  (`docker.events_cache_seconds`, default 30s) so it stays off the hot path;
  best-effort — if it fails the count degrades to `0` and the endpoint still 200s.
- When `docker_ok` is `false`, `totals` and `stats` are `null`.

### `GET /docker/stacks`

Per-Compose-project stacks, each with its containers and resource meters.
Containers with no Compose project label are grouped under an `"ungrouped"`
stack. Hot-path cost is three docker subprocesses (`ps`, `stats`, and a single
batched `docker inspect` over all container ids — reused for both the
per-container CPU limits and the volume names). Real volume sizes come from
`docker system df -v`, which is **cached** (`docker.df_cache_seconds`, default
60s) so the slow call only re-runs on cache expiry, not every poll. The `ps` +
`stats` snapshot is itself shared with `/docker/overview` within
`docker.stats_cache_seconds` (default 3s), so the two endpoints polled together
don't each shell out to `docker stats`.

```json
{
  "host": "pi-server",
  "docker_ok": true,
  "error": null,
  "stacks": [
    {
      "name": "blog",
      "meta": "wordpress · mariadb · redis",
      "health": "ok",
      "health_label": "Healthy",
      "mem_used_bytes": 612368384,
      "cpu_used_cores": 0.18,
      "disk_bytes": 197132288,
      "containers": [
        {
          "id": "a1b2c3d4e5f6",
          "name": "blog-wordpress-1",
          "service": "wordpress",
          "image": "wordpress:6.5",
          "project": "blog",
          "state": "ok",
          "state_raw": "running",
          "status": "Up 2 hours (healthy)",
          "health": "healthy",
          "mem":  { "used_bytes": 268435456, "limit_bytes": 536870912, "percent": 50.0 },
          "cpu":  { "used_cores": 0.12, "used_percent": 12.0, "limit_cores": 1.5, "percent": 8.0 },
          "disk": { "bytes": 725614592, "rw_bytes": 188743680, "volumes_bytes": 536870912, "local_volumes": 2 }
        }
      ]
    }
  ]
}
```

Field notes and honest caveats:

- `state` is a UI bucket derived from the raw docker state + status:
  `"ok"` (running/healthy), `"warn"` (unhealthy, restarting, paused,
  `health: starting`), `"bad"` (created/exited/dead). `state_raw` and `status`
  are the untouched docker values; `health` is the healthcheck sub-state
  (`"healthy"` / `"unhealthy"` / `"starting"`) or `null` when the container has
  no healthcheck.
- Stack `health` precedence is **bad > warn > ok** — one stopped container marks
  the whole stack `bad`. `health_label` is a short human summary
  (`"Healthy"` / `"1 unhealthy"` / `"1 stopped"`).
- **RAM meters work**: `mem.limit_bytes` and `mem.percent` are populated when the
  container has an explicit memory limit. A limit within ~1% of host RAM (or
  none) is treated as *unlimited*, so `limit_bytes` and `percent` are `null` and
  the UI hatches the meter as "no limit".
- **CPU meters work**: `cpu.limit_cores` and `cpu.percent` (used ÷ limit) are
  populated when the container has a CPU limit, derived from a single batched
  `docker inspect` over all containers (`HostConfig.NanoCpus`, falling back to
  `CpuQuota`/`CpuPeriod`) — one extra subprocess, never one per container. They
  are `null` **only when the container genuinely has no CPU limit set**, in which
  case the UI hatches the meter as "no limit" (mirroring the RAM no-limit case).
  If the inspect call fails for any reason the endpoint still returns 200 with
  the limits degraded to `null`. `cpu.used_cores` / `cpu.used_percent` (usage)
  are always populated.
- **Per-container disk includes volumes**: `disk.rw_bytes` is the writable-layer
  size from `ps -s`; `disk.volumes_bytes` is the real on-disk size of the
  container's named volumes, joined from the batched `docker inspect` (which
  volumes it mounts) and the cached `docker system df -v` (each volume's size);
  `disk.bytes` is their sum. Because `df -v` is cached (see above), this stays
  Pi-light. Best-effort: if `inspect` or `df -v` fails, `volumes_bytes` degrades
  to `0` (disk falls back to the writable layer) and the endpoint still 200s.
  Bind mounts are excluded (docker tracks no size for them). `local_volumes` is
  the count of attached local volumes.

### `GET /docker/logs`

Live tail for a single container, oldest → newest (docker's natural order).
Issues one docker subprocess (`docker logs`).

| Param | Meaning |
|-------|---------|
| `container` | **Required.** Container id or name. **Whitelist-validated** (`[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}`) and passed after a literal `--`, so an option-looking or metacharacter-laden value can never reach the argv. |
| `tail` | Lines to tail (server default `docker.logs_default_tail` = 200; capped at `docker.logs_max_tail` = 1000). |
| `since` | Look-back: epoch **seconds** or a docker duration (`10m`, `2h`, `1h30m`). Also whitelist-validated. |

```
GET /docker/logs?container=blog-wordpress-1&tail=500&since=10m
```

```json
{
  "host": "pi-server",
  "container": "blog-wordpress-1",
  "lines": [
    { "ts": 1782331556, "message": "[core:notice] AH00094: Command line: 'apache2 -D FOREGROUND'" }
  ],
  "count": 1,
  "tail": 500
}
```

- `ts` is epoch **seconds** (parsed from docker's RFC3339 timestamp), or `null`
  for a line whose leading token isn't a timestamp; `message` is the log text.
- `tail` echoes the effective (capped) line count used.
- An invalid `container`/`since` value, a missing docker binary, a timeout, or a
  daemon error returns **`502`** (same shape as the Server Logs `journalctl`
  failure). Note this differs from `/docker/overview` + `/docker/stacks`, which
  report an unreachable daemon as a `200` banner state.

---

## Versioning policy

- **v1** = the shapes above. The dashboard should tolerate unknown extra fields
  (forward-compatible) and not assume a fixed disk count.
- Breaking changes (renamed/removed fields, changed units) will ship under a new
  prefix such as `/v2/metrics/...`, leaving v1 intact for older dashboards.
