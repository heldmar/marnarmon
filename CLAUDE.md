# MarNarMon — host agent (project guide)

Context for Claude Code / contributors working in this repo. This is the
**public, open-source host agent** (Apache-2.0). The dashboard is a separate
private repo under `dashboard/` and is **excluded by `.gitignore`** — do not
add commercial/dashboard details to this file or commit `dashboard/` here.

## What this is

A lightweight, self-hosted Linux monitoring agent (a small CloudWatch
alternative) that runs on any Linux host — primarily a Raspberry Pi 4B and
EC2/Lightsail. It collects CPU, RAM, network, and per-disk usage, stores rolling
history in SQLite, and serves it over a small FastAPI service. A separate
(commercial) dashboard consumes the API. The API is the only contract between
them — see `API.md`.

## Layout

```
install.sh / uninstall.sh   interactive installer / remover
config/config.example.yml   reference config
host/marnarmon/             Python package: collectors, db, api, collect, config
host/systemd/               unit templates (placeholders filled at install)
tests/test_collectors.py    parser + DB unit tests (fixture-based)
API.md                      the v1 host/dashboard HTTP contract
```

Installed paths on a host: code+venv `/opt/marnarmon`, config
`/etc/marnarmon/config.yml`, DB `/var/lib/marnarmon/metrics.db`, units in
`/etc/systemd/system/marnarmon-*`.

## Design decisions (respect these)

- **No psutil.** Read `/proc/stat`, `/proc/meminfo`, `/proc/net/dev`,
  `/proc/loadavg`, `/proc/uptime`, and `os.statvfs` directly. Keeps it portable
  across ARM (Pi) and x86 (EC2) with minimal deps.
- **CPU% and network rates are deltas vs the previous stored SQLite sample**,
  not in-cycle sleeps. The collector is stateless per run; state lives in the DB.
- **systemd timer** runs the oneshot collector every N minutes; the API is a
  separate long-running uvicorn unit. Both run as the unprivileged `marnarmon`
  user with hardening.
- **venv at `/opt/marnarmon`** to avoid Debian/RPi PEP-668 "externally managed"
  pip errors.
- **Disks come from `/etc/fstab`** (mount column, excluding swap/none); the user
  selects which to track at install. Never hardcode mounts.
- **Config is YAML** at `/etc/marnarmon/config.yml`; nothing is hardcoded.
- **API binds `0.0.0.0` with an optional bearer token** (generated at install).

## Conventions

- Parser functions in `collectors.py` take raw text so they're unit-testable
  with fixtures — keep that pattern; add fixtures to `tests/` for new parsers.
- Timestamps are Unix **seconds** UTC; sizes in **bytes**; net rates in
  **bytes/sec**. Don't change units without versioning the API (`/v2/...`).
- `install.sh` must stay **idempotent** and distro-aware (apt/dnf/yum/apk).

## Dev / test

```bash
cd host && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
MARNARMON_CONFIG=../config/config.example.yml .venv/bin/python -m marnarmon.collect
MARNARMON_CONFIG=../config/config.example.yml .venv/bin/uvicorn marnarmon.api:app --port 8787
python tests/test_collectors.py     # no live /proc needed for parser tests
```

## Gotchas

- A recursive `find`/`ls` from the project root can be huge if `dashboard/`
  contains `node_modules` — scope listings (`-maxdepth`, `-prune`).
