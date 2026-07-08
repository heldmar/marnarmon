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
  "features": { "logs": false }
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
  "features": { "logs": false }
}
```

`503` is never returned here; a brand-new install with no samples yet returns
`status: "stale"` with `last_sample_ts: null`.

**`features`** is a capability map. `features.logs` is `true` when Server Logs
is enabled on this host (`logs.enabled` in config). The dashboard reads it to
decide whether to show the "Server Logs" section at all — when `false`, the
`/logs*` endpoints below return `503` and the UI hides the section entirely.

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

## Versioning policy

- **v1** = the shapes above. The dashboard should tolerate unknown extra fields
  (forward-compatible) and not assume a fixed disk count.
- Breaking changes (renamed/removed fields, changed units) will ship under a new
  prefix such as `/v2/metrics/...`, leaving v1 intact for older dashboards.
