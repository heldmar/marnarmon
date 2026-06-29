# MarNarMon

A lightweight, self-hosted server monitoring system — a small CloudWatch
replacement for Amazon EC2 / Lightsail that runs equally well on a Raspberry Pi
or any Linux box. It collects CPU, RAM, network, and per-disk usage straight
from `/proc` and `statvfs` (no `psutil`), stores rolling history in SQLite, and
serves it over a tiny FastAPI service. A React dashboard (in [`dashboard/`](dashboard/))
consumes the same API.

> **Status:** both parts are complete and open source (Apache-2.0): the
> host-side agent (this directory) and the React dashboard ([`dashboard/`](dashboard/),
> shipped as a Docker container). The HTTP contract between them is [`API.md`](API.md).

## What it does

- **Collector** — a oneshot Python script run by a systemd **timer** every *N*
  minutes. Reads CPU (`/proc/stat`), RAM (`/proc/meminfo`), network
  (`/proc/net/dev`), load (`/proc/loadavg`), uptime, and disk usage
  (`os.statvfs`) for each configured mount point. Writes a snapshot to SQLite
  and prunes rows past the retention window.
- **API** — a FastAPI/uvicorn service exposing the stored data:
  - `GET /health` — liveness + age of the last sample
  - `GET /metrics/current` — latest snapshot (CPU/RAM/net/load + per-disk)
  - `GET /metrics/history?window=24h` — time series (`window` accepts `30m`,
    `24h`, `7d`, or `?minutes=N`)
- **Config-driven** — everything lives in `/etc/marnarmon/config.yml`: tracked
  mount points, collection interval, retention, API bind/port, and an optional
  bearer token. Nothing is hardcoded.

## Install

On the target host (Raspberry Pi, EC2, Lightsail, …):

```bash
git clone <your-repo> marnarmon && cd marnarmon
sudo ./install.sh
```

The installer is interactive. It will:

1. Install `python3` + `venv` (apt/dnf/yum/apk aware).
2. Create a `marnarmon` system user.
3. Ask for host name, collection interval, retention, API bind address/port,
   and whether to enable a bearer token (auto-generated).
4. List the mount points found in `/etc/fstab` (with live usage) and let you
   pick which disks to track.
5. Deploy the code to `/opt/marnarmon`, build a venv, write the config,
   install and enable the systemd units, run one collection, and health-check
   the API.

Re-running `install.sh` is safe — it redeploys code and reapplies config.

### Layout

```
install.sh / uninstall.sh     interactive installer / remover
config/config.example.yml     reference config
host/marnarmon/               Python package (collectors, db, api, collect)
host/systemd/                 unit templates (placeholders filled at install)
tests/test_collectors.py      parser + DB unit tests
```

Installed paths:

| Path | Purpose |
|------|---------|
| `/opt/marnarmon` | code + virtualenv |
| `/etc/marnarmon/config.yml` | configuration |
| `/var/lib/marnarmon/metrics.db` | SQLite history |
| `/etc/systemd/system/marnarmon-*.{service,timer}` | systemd units |

## Configuration

Edit `/etc/marnarmon/config.yml`, then:

```bash
sudo systemctl restart marnarmon-api.service        # API changes
# collector picks up config on its next timed run; force one with:
sudo systemctl start marnarmon-collector.service
```

If you change the interval, also update `OnUnitActiveSec` in
`marnarmon-collector.timer` (or just re-run `install.sh`).

## Usage examples

```bash
# No auth
curl http://HOST:8787/metrics/current
curl "http://HOST:8787/metrics/history?window=24h"

# With a token
curl -H "Authorization: Bearer <token>" http://HOST:8787/metrics/current
```

## Operate

```bash
systemctl status marnarmon-collector.timer
systemctl list-timers marnarmon-collector.timer
journalctl -u marnarmon-api.service -f
journalctl -u marnarmon-collector.service -f
```

## Develop / test

```bash
cd host
python3 -m venv .venv && . .venv/bin/python -m pip install -r requirements.txt
MARNARMON_CONFIG=../config/config.example.yml python -m marnarmon.collect
MARNARMON_CONFIG=../config/config.example.yml uvicorn marnarmon.api:app --port 8787

# tests (no /proc fixtures needed for parsers)
python ../tests/test_collectors.py
```

## Uninstall

```bash
sudo ./uninstall.sh
```

## Security notes

- Bind the API to `127.0.0.1` if the dashboard runs on the same host; use
  `0.0.0.0` only on a trusted LAN, ideally with the bearer token enabled.
- The service runs as an unprivileged `marnarmon` user with systemd hardening
  (`ProtectSystem`, `ProtectHome`, `NoNewPrivileges`, restricted
  `ReadWritePaths`).
