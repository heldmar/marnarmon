"""SQLite storage for MarNarMon metrics.

Two tables:
  snapshots    - one row per collection cycle (CPU/RAM/net/load/uptime)
  disk_usage   - one row per tracked mount per cycle (FK by timestamp)

Cumulative counters (cpu_total/cpu_idle, net_rx_bytes/net_tx_bytes) are stored
so the next cycle can compute deltas. WAL mode keeps the API's reads from
blocking the collector's writes.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ts                INTEGER PRIMARY KEY,   -- unix seconds
    cpu_percent       REAL,
    cpu_total         INTEGER,
    cpu_idle          INTEGER,
    mem_total_kb      INTEGER,
    mem_available_kb  INTEGER,
    mem_used_kb       INTEGER,
    mem_percent       REAL,
    net_rx_bytes      INTEGER,
    net_tx_bytes      INTEGER,
    net_rx_rate       REAL,                  -- bytes/sec since previous sample
    net_tx_rate       REAL,
    load1             REAL,
    load5             REAL,
    load15            REAL,
    uptime_seconds    REAL
);

CREATE TABLE IF NOT EXISTS disk_usage (
    ts           INTEGER NOT NULL,
    mount        TEXT NOT NULL,
    total_bytes  INTEGER,
    used_bytes   INTEGER,
    free_bytes   INTEGER,
    percent      REAL,
    PRIMARY KEY (ts, mount)
);

CREATE INDEX IF NOT EXISTS idx_disk_usage_ts ON disk_usage(ts);
"""


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def latest_snapshot(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM snapshots ORDER BY ts DESC LIMIT 1")
    return cur.fetchone()


def insert_snapshot(
    conn: sqlite3.Connection, ts: int, snap: Dict, disks: List[Dict]
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO snapshots (
            ts, cpu_percent, cpu_total, cpu_idle,
            mem_total_kb, mem_available_kb, mem_used_kb, mem_percent,
            net_rx_bytes, net_tx_bytes, net_rx_rate, net_tx_rate,
            load1, load5, load15, uptime_seconds
        ) VALUES (
            :ts, :cpu_percent, :cpu_total, :cpu_idle,
            :mem_total_kb, :mem_available_kb, :mem_used_kb, :mem_percent,
            :net_rx_bytes, :net_tx_bytes, :net_rx_rate, :net_tx_rate,
            :load1, :load5, :load15, :uptime_seconds
        )
        """,
        {"ts": ts, **snap},
    )
    for d in disks:
        conn.execute(
            """
            INSERT OR REPLACE INTO disk_usage (
                ts, mount, total_bytes, used_bytes, free_bytes, percent
            ) VALUES (:ts, :mount, :total_bytes, :used_bytes, :free_bytes, :percent)
            """,
            {"ts": ts, **d},
        )
    conn.commit()


def prune(conn: sqlite3.Connection, retention_days: int, now: Optional[int] = None) -> int:
    """Delete rows older than retention_days. Returns rows removed from snapshots."""
    now = now if now is not None else int(time.time())
    cutoff = now - retention_days * 86400
    cur = conn.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
    conn.execute("DELETE FROM disk_usage WHERE ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def current(conn: sqlite3.Connection) -> Optional[Dict]:
    """Latest snapshot plus its disk rows, as plain dicts for JSON output."""
    snap = latest_snapshot(conn)
    if snap is None:
        return None
    disks = conn.execute(
        "SELECT mount, total_bytes, used_bytes, free_bytes, percent "
        "FROM disk_usage WHERE ts = ? ORDER BY mount",
        (snap["ts"],),
    ).fetchall()
    out = dict(snap)
    out["disks"] = [dict(d) for d in disks]
    return out


def history(conn: sqlite3.Connection, since_ts: int) -> Dict:
    """Time series of snapshots and per-mount disk usage since since_ts."""
    snaps = conn.execute(
        "SELECT ts, cpu_percent, mem_percent, net_rx_rate, net_tx_rate, "
        "load1, load5, load15 FROM snapshots WHERE ts >= ? ORDER BY ts ASC",
        (since_ts,),
    ).fetchall()
    disk_rows = conn.execute(
        "SELECT ts, mount, used_bytes, total_bytes, percent FROM disk_usage "
        "WHERE ts >= ? ORDER BY ts ASC",
        (since_ts,),
    ).fetchall()

    disks: Dict[str, List[Dict]] = {}
    for r in disk_rows:
        disks.setdefault(r["mount"], []).append(
            {
                "ts": r["ts"],
                "used_bytes": r["used_bytes"],
                "total_bytes": r["total_bytes"],
                "percent": r["percent"],
            }
        )
    return {
        "snapshots": [dict(s) for s in snaps],
        "disks": disks,
    }
