"""Unit tests for the /proc parsers and SQLite layer.

These use fixture text (not the live /proc) so they are deterministic and run
anywhere, including CI and dev sandboxes. Run:

    cd host && python -m pytest ../tests -q
    # or, without pytest:
    python ../tests/test_collectors.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host"))

from marnarmon import collectors as c  # noqa: E402
from marnarmon import db as sdb  # noqa: E402

PROC_STAT = """cpu  100 0 50 800 50 0 0 0 0 0
cpu0 50 0 25 400 25 0 0 0 0 0
intr 12345
ctxt 67890
"""

PROC_STAT_LATER = """cpu  200 0 100 1600 100 0 0 0 0 0
cpu0 100 0 50 800 50 0 0 0 0 0
"""

PROC_MEMINFO = """MemTotal:        4000000 kB
MemFree:          500000 kB
MemAvailable:    2000000 kB
Buffers:          100000 kB
Cached:           800000 kB
"""

PROC_NET_DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1000      10    0    0    0     0          0         0     1000      10    0    0    0     0       0          0
  eth0: 5000      50    0    0    0     0          0         0     3000      30    0    0    0     0       0          0
 veth9: 9999      99    0    0    0     0          0         0     8888      88    0    0    0     0       0          0
"""


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        raise AssertionError(name)


def test_cpu():
    prev = c.parse_cpu(PROC_STAT)        # total=1000, idle=800+50=850
    cur = c.parse_cpu(PROC_STAT_LATER)   # total=2000, idle=1600+100=1700
    check("parse_cpu totals", prev == (1000, 850) and cur == (2000, 1700))
    # delta total=1000, delta idle=850 -> busy=150 -> 15%
    check("cpu_percent 15%", c.cpu_percent(prev, cur) == 15.0)
    check("cpu_percent no movement = 0", c.cpu_percent(cur, cur) == 0.0)


def test_mem():
    m = c.parse_meminfo(PROC_MEMINFO)
    check("mem_total", m["mem_total_kb"] == 4000000)
    check("mem_available used", m["mem_used_kb"] == 2000000)  # 4M - 2M available
    check("mem_percent 50", m["mem_percent"] == 50.0)


def test_net():
    # auto mode: excludes lo and veth9 -> only eth0
    rx, tx = c.parse_net_dev(PROC_NET_DEV)
    check("net auto rx (eth0 only)", rx == 5000)
    check("net auto tx (eth0 only)", tx == 3000)
    # explicit interface filter
    rx2, tx2 = c.parse_net_dev(PROC_NET_DEV, ["eth0", "lo"])
    check("net explicit rx (eth0+lo)", rx2 == 6000)
    # rate: 6000 bytes over 60s = 100 B/s
    check("rate 100 B/s", c.rate(0, 6000, 60) == 100.0)
    check("rate counter reset -> 0", c.rate(6000, 10, 60) == 0.0)


def test_loadavg():
    l1, l5, l15 = c.parse_loadavg("0.50 0.75 1.00 2/345 6789\n")
    check("loadavg parse", (l1, l5, l15) == (0.5, 0.75, 1.0))


def test_disk_live():
    # statvfs on a path that always exists
    d = c.read_disk("/")
    check("read_disk returns dict", isinstance(d, dict))
    check("read_disk percent in range", 0.0 <= d["percent"] <= 100.0)
    check("read_disk missing mount -> None", c.read_disk("/no/such/mount/xyz") is None)


def test_db_roundtrip(tmp_path="/tmp/marnarmon_test.db"):
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    conn = sdb.connect(tmp_path)
    sdb.init_db(conn)
    snap = {
        "cpu_percent": 12.5, "cpu_total": 1000, "cpu_idle": 850,
        "mem_total_kb": 4000000, "mem_available_kb": 2000000,
        "mem_used_kb": 2000000, "mem_percent": 50.0,
        "net_rx_bytes": 5000, "net_tx_bytes": 3000,
        "net_rx_rate": 100.0, "net_tx_rate": 50.0,
        "load1": 0.5, "load5": 0.75, "load15": 1.0, "uptime_seconds": 1234.0,
    }
    disks = [{"mount": "/", "total_bytes": 100, "used_bytes": 40,
              "free_bytes": 60, "percent": 40.0}]
    sdb.insert_snapshot(conn, 1000, snap, disks)
    cur = sdb.current(conn)
    check("db current cpu", cur["cpu_percent"] == 12.5)
    check("db current disks", cur["disks"][0]["mount"] == "/")

    sdb.insert_snapshot(conn, 2000, snap, disks)
    hist = sdb.history(conn, 0)
    check("db history len 2", len(hist["snapshots"]) == 2)
    check("db history disk series", len(hist["disks"]["/"]) == 2)

    # prune: with now=2000 and retention 0 days, cutoff=2000 -> ts<2000 removed
    removed = sdb.prune(conn, retention_days=0, now=2000)
    check("db prune removed old row", removed == 1)
    conn.close()
    os.remove(tmp_path)


def main():
    tests = [test_cpu, test_mem, test_net, test_loadavg, test_disk_live, test_db_roundtrip]
    print("Running MarNarMon collector tests...")
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
