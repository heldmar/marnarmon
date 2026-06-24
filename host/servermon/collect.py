"""One collection cycle: read metrics, compute deltas, store, prune.

Invoked by the systemd timer (servermon-collector.timer) as a oneshot. Keeping
it stateless-per-process (state lives in SQLite) makes it robust to restarts.

Run manually:  python -m servermon.collect
"""
from __future__ import annotations

import sys
import time

from . import collectors as c
from . import db
from .config import load_config


def run_once() -> dict:
    cfg = load_config()
    conn = db.connect(cfg.db_path)
    db.init_db(conn)

    now = int(time.time())
    prev = db.latest_snapshot(conn)

    cpu_total, cpu_idle = c.read_cpu()
    mem = c.read_meminfo()
    rx, tx = c.read_net_dev(cfg.interfaces)

    try:
        load1, load5, load15 = c.read_loadavg()
    except (OSError, ValueError):
        load1 = load5 = load15 = 0.0
    try:
        uptime = c.read_uptime()
    except (OSError, ValueError):
        uptime = 0.0

    # Deltas against previous stored sample.
    if prev is not None:
        cpu_pct = c.cpu_percent(
            (prev["cpu_total"], prev["cpu_idle"]), (cpu_total, cpu_idle)
        )
        seconds = max(1, now - prev["ts"])
        rx_rate = c.rate(prev["net_rx_bytes"], rx, seconds)
        tx_rate = c.rate(prev["net_tx_bytes"], tx, seconds)
    else:
        cpu_pct = 0.0
        rx_rate = 0.0
        tx_rate = 0.0

    snap = {
        "cpu_percent": cpu_pct,
        "cpu_total": cpu_total,
        "cpu_idle": cpu_idle,
        "mem_total_kb": mem["mem_total_kb"],
        "mem_available_kb": mem["mem_available_kb"],
        "mem_used_kb": mem["mem_used_kb"],
        "mem_percent": mem["mem_percent"],
        "net_rx_bytes": rx,
        "net_tx_bytes": tx,
        "net_rx_rate": rx_rate,
        "net_tx_rate": tx_rate,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "uptime_seconds": uptime,
    }
    disks = c.read_disks(cfg.disks)

    db.insert_snapshot(conn, now, snap, disks)
    removed = db.prune(conn, cfg.retention_days, now)
    conn.close()

    return {"ts": now, "cpu_percent": cpu_pct, "disks": len(disks), "pruned": removed}


def main() -> int:
    try:
        result = run_once()
    except Exception as exc:  # noqa: BLE001 - surface to journald and exit non-zero
        print(f"servermon collect failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"servermon collect ok ts={result['ts']} "
        f"cpu={result['cpu_percent']}% disks={result['disks']} "
        f"pruned={result['pruned']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
