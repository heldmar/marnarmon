# MarNarMon API contract (v1)

This is the stable boundary between the **host agent** (free, this repo) and the
**dashboard** (commercial, separate repo). Both sides build against this spec.
Treat it as versioned: additive changes are fine; breaking changes get a new
major version and a new path prefix.

- Base URL: `http://<host>:<port>` (default port `8787`)
- All responses are JSON.
- **Auth:** if a bearer token is configured (`api.token` in `config.yml`), every
  endpoint except `/` requires `Authorization: Bearer <token>`. Otherwise no
  auth is required.
- **CORS:** `GET` is allowed from any origin so a browser dashboard can call it.
- **Times:** all timestamps are Unix epoch **seconds** (integer, UTC).
- **Bytes:** all sizes are bytes. Network rates are **bytes per second**,
  averaged over the interval since the previous sample.

---

## `GET /`

Open (no auth). Service banner.

```json
{ "service": "marnarmon", "version": "0.1.0", "host": "pi-server" }
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
  "interval_minutes": 5
}
```

`503` is never returned here; a brand-new install with no samples yet returns
`status: "stale"` with `last_sample_ts: null`.

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

## Versioning policy

- **v1** = the shapes above. The dashboard should tolerate unknown extra fields
  (forward-compatible) and not assume a fixed disk count.
- Breaking changes (renamed/removed fields, changed units) will ship under a new
  prefix such as `/v2/metrics/...`, leaving v1 intact for older dashboards.
