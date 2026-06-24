"""Metric collectors that read directly from /proc and statvfs.

No third-party dependencies (no psutil). Parsing functions take raw text so
they can be unit-tested with fixtures; the read_* wrappers do the actual I/O.

CPU percent and network rates are computed from deltas against the previous
stored sample (see collect.py), so cumulative counters are returned here.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

# Interface name prefixes excluded from auto-detected network totals.
_VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "veth", "br-", "virbr", "vnet", "tap")


# --------------------------------------------------------------------------- #
# CPU
# --------------------------------------------------------------------------- #
def parse_cpu(stat_text: str) -> Tuple[int, int]:
    """Return (total_jiffies, idle_jiffies) from /proc/stat contents.

    Uses the aggregate 'cpu' line. idle = idle + iowait.
    """
    for line in stat_text.splitlines():
        if line.startswith("cpu ") or line.startswith("cpu\t"):
            parts = line.split()[1:]
            nums = [int(p) for p in parts]
            # user nice system idle iowait irq softirq steal guest guest_nice
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            total = sum(nums)
            return total, idle
    raise ValueError("No aggregate 'cpu' line found in /proc/stat")


def cpu_percent(prev: Tuple[int, int], cur: Tuple[int, int]) -> float:
    """CPU utilisation percent between two (total, idle) samples."""
    prev_total, prev_idle = prev
    cur_total, cur_idle = cur
    d_total = cur_total - prev_total
    d_idle = cur_idle - prev_idle
    if d_total <= 0:
        return 0.0
    pct = (d_total - d_idle) / d_total * 100.0
    return round(max(0.0, min(100.0, pct)), 2)


def read_cpu(proc_stat: str = "/proc/stat") -> Tuple[int, int]:
    with open(proc_stat, "r", encoding="utf-8") as fh:
        return parse_cpu(fh.read())


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
def parse_meminfo(text: str) -> Dict[str, float]:
    """Parse /proc/meminfo into total/available/used KiB and used percent."""
    values: Dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields:
            values[key.strip()] = int(fields[0])  # value in kB

    total = values.get("MemTotal", 0)
    # MemAvailable is the kernel's best estimate; fall back if absent.
    available = values.get("MemAvailable")
    if available is None:
        available = (
            values.get("MemFree", 0)
            + values.get("Buffers", 0)
            + values.get("Cached", 0)
        )
    used = max(0, total - available)
    percent = round(used / total * 100.0, 2) if total else 0.0
    return {
        "mem_total_kb": total,
        "mem_available_kb": available,
        "mem_used_kb": used,
        "mem_percent": percent,
    }


def read_meminfo(proc_meminfo: str = "/proc/meminfo") -> Dict[str, float]:
    with open(proc_meminfo, "r", encoding="utf-8") as fh:
        return parse_meminfo(fh.read())


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
def _is_real_iface(name: str) -> bool:
    return not any(name.startswith(p) for p in _VIRTUAL_IFACE_PREFIXES)


def parse_net_dev(
    text: str, interfaces: Optional[Iterable[str]] = None
) -> Tuple[int, int]:
    """Return cumulative (rx_bytes, tx_bytes) summed over interfaces.

    If `interfaces` is None or empty, auto-select real (non-virtual) interfaces.
    """
    wanted = set(interfaces or [])
    rx_total = 0
    tx_total = 0
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        fields = rest.split()
        if len(fields) < 16:
            continue
        if wanted:
            if name not in wanted:
                continue
        elif not _is_real_iface(name):
            continue
        rx_total += int(fields[0])   # receive bytes
        tx_total += int(fields[8])   # transmit bytes
    return rx_total, tx_total


def read_net_dev(
    interfaces: Optional[Iterable[str]] = None, proc_net_dev: str = "/proc/net/dev"
) -> Tuple[int, int]:
    with open(proc_net_dev, "r", encoding="utf-8") as fh:
        return parse_net_dev(fh.read(), interfaces)


def rate(prev_bytes: int, cur_bytes: int, seconds: float) -> float:
    """Bytes-per-second between two cumulative counter samples."""
    if seconds <= 0:
        return 0.0
    delta = cur_bytes - prev_bytes
    if delta < 0:  # counter reset (reboot / iface reset)
        return 0.0
    return round(delta / seconds, 2)


# --------------------------------------------------------------------------- #
# Load average & uptime (cheap extras, useful for the dashboard)
# --------------------------------------------------------------------------- #
def parse_loadavg(text: str) -> Tuple[float, float, float]:
    parts = text.split()
    return float(parts[0]), float(parts[1]), float(parts[2])


def read_loadavg(proc_loadavg: str = "/proc/loadavg") -> Tuple[float, float, float]:
    with open(proc_loadavg, "r", encoding="utf-8") as fh:
        return parse_loadavg(fh.read())


def read_uptime(proc_uptime: str = "/proc/uptime") -> float:
    with open(proc_uptime, "r", encoding="utf-8") as fh:
        return float(fh.read().split()[0])


# --------------------------------------------------------------------------- #
# Disk (statvfs)
# --------------------------------------------------------------------------- #
def read_disk(mount: str) -> Optional[Dict[str, float]]:
    """Disk usage for a mount point via os.statvfs. None if unavailable."""
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize          # available to non-root
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    usable = used + free
    percent = round(used / usable * 100.0, 2) if usable else 0.0
    return {
        "mount": mount,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent": percent,
    }


def read_disks(mounts: Iterable[str]) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for m in mounts:
        d = read_disk(m)
        if d is not None:
            out.append(d)
    return out
