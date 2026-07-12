"""Read Docker container/stack resource usage via the `docker` CLI.

Design mirrors logs.py (and collectors.py): pure functions — argv building, size
parsing, JSON/text parsing, stack grouping — are separated from the thin
subprocess wrappers that do the actual I/O, so the tricky parsing/grouping logic
is unit-testable with fixtures and no live docker daemon.

We shell out to `docker` and read its primitive output (same "no library, read
the primitive directly" stance as the /proc collectors and journalctl — not the
docker SDK, which is a heavy dependency and needs the API socket bound). Nothing
here is stored; every value is read live per request.

This module is only reachable when docker.enabled is true in config and the
service user can reach the docker socket; otherwise the CLI returns a permission
error which api.py turns into a friendly "daemon unreachable" banner.

Cost note (this runs on a Pi): the live snapshot (`docker ps -a -s` +
`docker stats --no-stream`) is fetched once per poll cycle and SHARED between
/docker/overview and /docker/stacks via a short-TTL in-memory cache, so the two
endpoints (fired together each cycle) don't shell out twice. The slow calls —
`docker system df -v` (per-volume sizes) and `docker events` (24h restart
history) — sit behind their own longer TTL caches, so they run only on cache
expiry, not every 5s. Network/block rates are computed as in-memory deltas
between successive snapshots (bytes/sec), mirroring how the host collector
derives rates from consecutive SQLite samples. Every extra datum is best-effort:
if inspect / df -v / events fails, that datum degrades (rate 0, volumes 0,
restarts 0, limit None) and the endpoint still returns 200.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from typing import Dict, List, Optional, Sequence

# The Compose labels docker writes on every container it creates. We group by
# project and read the service name straight off the label — no inspect needed.
_LABEL_PROJECT = "com.docker.compose.project"
_LABEL_SERVICE = "com.docker.compose.service"

# Bucket for containers with no Compose project label (plain `docker run`).
UNGROUPED = "ungrouped"

# A safe container reference: an id (hex) or a name. Docker names/ids are
# [a-zA-Z0-9][a-zA-Z0-9_.-]*; reject anything else so a caller can never sneak
# an option-looking value (e.g. "--since=…") or shell metacharacter through.
_CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")

# --since accepts either an epoch-second integer or a docker duration like
# "10m", "2h", "1h30m". Whitelist both so nothing else reaches the argv.
_SINCE_RE = re.compile(r"^(?:\d{1,19}|\d+[smh](?:\d+[smh])*)$")

# SI (1000) and binary (1024) unit suffixes as docker emits them: stats MemUsage
# uses MiB/GiB, while NetIO/BlockIO/df/ps-Size use kB/MB/GB. Handle both.
_SIZE_UNITS = {
    "": 1,
    "b": 1,
    "kb": 1000,
    "mb": 1000 ** 2,
    "gb": 1000 ** 3,
    "tb": 1000 ** 4,
    "pb": 1000 ** 5,
    "kib": 1024,
    "mib": 1024 ** 2,
    "gib": 1024 ** 3,
    "tib": 1024 ** 4,
    "pib": 1024 ** 5,
}
_SIZE_RE = re.compile(r"^\s*([\d.]+)\s*([a-zA-Z]*)\s*$")

# Health / lifecycle sub-state pulled out of the ps "Status" string, e.g.
# "Up 2 hours (healthy)" or "Up 5s (health: starting)".
_HEALTH_RE = re.compile(r"\((healthy|unhealthy|health: starting)\)")


class DockerError(RuntimeError):
    """Raised when the docker CLI cannot be run or fails (missing binary,
    timeout, daemon unreachable, permission denied). api.py turns this into a
    friendly HTTP error / "daemon unreachable" banner."""


# --------------------------------------------------------------------------- #
# Small pure helpers (size/percent parsing)
# --------------------------------------------------------------------------- #
def parse_size(text) -> float:
    """Parse a docker size string ("1.2GB", "180MB", "5.5MiB", "0B") to bytes.
    Tolerant: returns 0.0 for empty/unparseable input rather than raising."""
    if text is None:
        return 0.0
    m = _SIZE_RE.match(str(text))
    if not m:
        return 0.0
    try:
        value = float(m.group(1))
    except ValueError:
        return 0.0
    return value * _SIZE_UNITS.get(m.group(2).lower(), 1)


def parse_size_pair(text, sep: str = "/") -> tuple:
    """Parse a "<a> / <b>" pair (e.g. MemUsage "5.5MiB / 1.9GiB", NetIO
    "1.2kB / 3.4kB") into a (bytes_a, bytes_b) tuple."""
    parts = str(text or "").split(sep)
    a = parse_size(parts[0]) if len(parts) >= 1 else 0.0
    b = parse_size(parts[1]) if len(parts) >= 2 else 0.0
    return a, b


def parse_percent(text) -> float:
    """Parse a docker percent string ("1.23%") to a float. 0.0 on failure."""
    try:
        return float(str(text or "").replace("%", "").strip())
    except ValueError:
        return 0.0


def _host_mem_total_bytes() -> int:
    """Host RAM total, read straight from /proc/meminfo (no psutil), used as the
    reference for the aggregate memory gauge and to detect containers with no
    explicit memory limit (docker reports the host total as their 'limit')."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024  # kB -> bytes
    except OSError:
        pass
    return 0


def _host_disk_total_bytes(path: str = "/") -> int:
    """Total size of the filesystem backing docker's data (best-effort: statvfs
    of `/`). Reference for the aggregate disk gauge's percent-of-host."""
    try:
        st = os.statvfs(path)
        return st.f_blocks * st.f_frsize
    except OSError:
        return 0


# --------------------------------------------------------------------------- #
# State / health classification (pure)
# --------------------------------------------------------------------------- #
def classify_state(state: str, status: str) -> str:
    """Map a container's raw State + Status into the UI dot bucket:

        ok   — running and healthy (or no healthcheck)
        warn — running-but-unhealthy, restarting, paused, health: starting
        bad  — exited / dead / created (not running)
    """
    state = (state or "").lower()
    health = health_label(status)
    if state == "running":
        if health == "unhealthy":
            return "warn"
        return "ok"
    if state in ("restarting", "paused"):
        return "warn"
    # created / exited / dead / removing / unknown
    return "bad"


def health_label(status: str) -> Optional[str]:
    """Extract the healthcheck sub-state ("healthy"/"unhealthy"/"starting") from
    a ps Status string, or None when the container has no healthcheck."""
    m = _HEALTH_RE.search(status or "")
    if not m:
        return None
    token = m.group(1)
    return "starting" if token.startswith("health:") else token


# --------------------------------------------------------------------------- #
# Argument building (pure)
# --------------------------------------------------------------------------- #
def build_stats_args(docker_path: str = "docker") -> List[str]:
    """argv for a one-shot per-container resource snapshot (cheap)."""
    return [docker_path, "stats", "--no-stream", "--format", "{{json .}}"]


def build_ps_args(docker_path: str = "docker") -> List[str]:
    """argv listing all containers (running + stopped) with sizes + labels.

    -a includes stopped containers (their volumes still consume disk); -s adds
    the writable-layer/virtual Size column.
    """
    return [docker_path, "ps", "-a", "-s", "--format", "{{json .}}"]


def build_system_df_args(docker_path: str = "docker", verbose: bool = False) -> List[str]:
    """argv for disk usage. The summary form (default) is cheap and gives the
    images/containers/volumes totals for the aggregate disk gauge. `verbose`
    (`-v`) is slow — only for per-object breakdowns."""
    args = [docker_path, "system", "df", "--format", "{{json .}}"]
    if verbose:
        args.insert(3, "-v")  # docker system df -v --format {{json .}}
    return args


def build_logs_args(
    container: str,
    *,
    tail: int = 200,
    since: Optional[str] = None,
    timestamps: bool = True,
    docker_path: str = "docker",
) -> List[str]:
    """Build the `docker logs` argv for one container's live tail.

    Guards against argv/option injection: the container ref is validated against
    a strict whitelist and passed after a literal "--" so a hostile name like
    "-f" or "--since=…" can never be treated as a flag.
    """
    if not _CONTAINER_RE.match(container or ""):
        raise DockerError("invalid container reference")

    args = [docker_path, "logs", "--tail", str(int(tail))]
    if timestamps:
        args.append("--timestamps")
    if since:
        if not _SINCE_RE.match(str(since)):
            raise DockerError("invalid --since value")
        args.append(f"--since={since}")
    args.append("--")
    args.append(container)
    return args


def build_inspect_args(container_ids: Sequence[str], docker_path: str = "docker") -> List[str]:
    """Build a SINGLE `docker inspect <id1> <id2> …` argv for all containers in
    one call (docker inspect returns a JSON array for the whole batch), so the
    per-container CPU limit costs exactly one extra subprocess — never one per
    container.

    Every id is validated with the same strict whitelist as build_logs_args and
    passed after a literal "--", so a hostile id can't become a flag / shell
    token. Returns [] for an empty id list so the caller can skip the call.
    """
    ids = [str(c) for c in (container_ids or []) if c]
    if not ids:
        return []
    for cid in ids:
        if not _CONTAINER_RE.match(cid):
            raise DockerError("invalid container reference")
    return [docker_path, "inspect", "--", *ids]


def build_events_args(
    since_epoch: float, until_epoch: float, docker_path: str = "docker"
) -> List[str]:
    """argv for a HISTORICAL (non-blocking) `docker events` query bounded by
    --since/--until epoch seconds, filtered to container restart events. Without
    --until, `docker events` would stream forever; the explicit window makes it
    return the 24h restart history and exit. Epochs are ints (our own values,
    never user input) so nothing untrusted reaches the argv."""
    return [
        docker_path,
        "events",
        "--since",
        str(int(since_epoch)),
        "--until",
        str(int(until_epoch)),
        "--filter",
        "type=container",
        "--filter",
        "event=restart",
        "--format",
        "{{json .}}",
    ]


# --------------------------------------------------------------------------- #
# Output parsing (pure)
# --------------------------------------------------------------------------- #
def _iter_json_lines(raw_stdout: str):
    """Yield parsed dicts from docker's `--format {{json .}}` output (one JSON
    object per line). Blank/malformed lines are skipped, matching logs.py."""
    for line in raw_stdout.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            yield rec


def parse_stats(raw_stdout: str) -> Dict[str, dict]:
    """Parse `docker stats --no-stream --format {{json .}}` into a dict keyed by
    both container id and name, so a caller can join by whichever ps exposes.

    Each value: cpu_percent, mem_used/mem_limit (bytes), net_rx/net_tx (bytes,
    cumulative since container start — docker has no per-interval rate here),
    block_read/block_write (bytes)."""
    out: Dict[str, dict] = {}
    for rec in _iter_json_lines(raw_stdout):
        mem_used, mem_limit = parse_size_pair(rec.get("MemUsage"))
        net_rx, net_tx = parse_size_pair(rec.get("NetIO"))
        blk_r, blk_w = parse_size_pair(rec.get("BlockIO"))
        entry = {
            "id": rec.get("ID") or rec.get("Container") or "",
            "name": rec.get("Name") or "",
            "cpu_percent": parse_percent(rec.get("CPUPerc")),
            "mem_used": mem_used,
            "mem_limit": mem_limit,
            "mem_percent": parse_percent(rec.get("MemPerc")),
            "net_rx": net_rx,
            "net_tx": net_tx,
            "block_read": blk_r,
            "block_write": blk_w,
        }
        if entry["id"]:
            out[entry["id"]] = entry
            out[entry["id"][:12]] = entry  # short id, as ps -a often prints
        if entry["name"]:
            out[entry["name"]] = entry
    return out


def parse_ps(raw_stdout: str) -> List[dict]:
    """Parse `docker ps -a -s --format {{json .}}` into normalized container
    dicts: identity, image, raw + classified state, Compose project/service, and
    the writable-layer / virtual disk sizes parsed from the "Size" column
    ("180MB (virtual 600MB)")."""
    out: List[dict] = []
    for rec in _iter_json_lines(raw_stdout):
        labels = _parse_labels(rec.get("Labels"))
        status = rec.get("Status") or ""
        state = rec.get("State") or ""
        rw_bytes, virtual_bytes = _parse_ps_size(rec.get("Size"))
        try:
            volumes = int(rec.get("LocalVolumes") or 0)
        except (TypeError, ValueError):
            volumes = 0
        out.append(
            {
                "id": rec.get("ID") or "",
                "name": rec.get("Names") or "",
                "image": rec.get("Image") or "",
                "state_raw": state,
                "status": status,
                "state": classify_state(state, status),
                "health": health_label(status),
                "project": labels.get(_LABEL_PROJECT) or "",
                "service": labels.get(_LABEL_SERVICE) or (rec.get("Names") or ""),
                "rw_bytes": rw_bytes,
                "virtual_bytes": virtual_bytes,
                "local_volumes": volumes,
            }
        )
    return out


def _parse_labels(raw) -> Dict[str, str]:
    """Docker prints Labels as a single comma-joined "k=v,k=v" string. Parse it
    back into a dict (values may themselves contain no comma — docker escapes
    none, so this is the documented format)."""
    labels: Dict[str, str] = {}
    if not raw:
        return labels
    for pair in str(raw).split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            labels[k.strip()] = v.strip()
    return labels


def _parse_ps_size(raw) -> tuple:
    """Parse the ps Size column "180MB (virtual 600MB)" → (writable_bytes,
    virtual_bytes). The writable layer is the container's own on-disk footprint;
    virtual includes the shared image layers."""
    if not raw:
        return 0.0, 0.0
    text = str(raw)
    virtual = 0.0
    m = re.search(r"virtual\s+([\d.]+\s*[a-zA-Z]+)", text)
    if m:
        virtual = parse_size(m.group(1))
    writable = parse_size(text.split("(")[0])
    return writable, virtual


def parse_system_df(raw_stdout: str) -> Dict[str, dict]:
    """Parse the summary `docker system df --format {{json .}}` (one row per
    Type: Images / Containers / Local Volumes / Build Cache) into a dict keyed by
    a normalized type ("images"/"containers"/"volumes"/"build_cache") with a
    size in bytes."""
    key_map = {
        "images": "images",
        "containers": "containers",
        "local volumes": "volumes",
        "build cache": "build_cache",
    }
    out: Dict[str, dict] = {}
    for rec in _iter_json_lines(raw_stdout):
        raw_type = str(rec.get("Type") or "").strip().lower()
        key = key_map.get(raw_type)
        if not key:
            continue
        out[key] = {
            "size_bytes": parse_size(rec.get("Size")),
            "reclaimable_bytes": parse_size(str(rec.get("Reclaimable") or "").split("(")[0]),
        }
    return out


def parse_inspect_cpu(raw_stdout: str) -> Dict[str, Optional[float]]:
    """Parse `docker inspect <ids…>` (a JSON array) into a map of container id ->
    CPU limit in cores, or None when the container has no CPU limit set.

    Cores are derived from HostConfig, cheaply and without a per-container call:
      - NanoCpus  (set by `--cpus`)  -> cores = NanoCpus / 1e9
      - else CpuQuota/CpuPeriod (`--cpu-quota`/`--cpu-period`, or `--cpus` on
        older daemons) -> cores = CpuQuota / CpuPeriod (period defaults to the
        kernel CFS default 100000 µs when unset).
      - else None (genuinely unlimited).
    Tolerant: malformed JSON, non-array payloads, and missing fields degrade to
    an empty map / None rather than raising."""
    try:
        data = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, list):
        return {}

    out: Dict[str, Optional[float]] = {}
    for obj in data:
        if not isinstance(obj, dict):
            continue
        cid = obj.get("Id") or obj.get("ID") or ""
        if not cid:
            continue
        limit = _cpu_limit_cores(obj.get("HostConfig") or {})
        out[cid] = limit
        out[cid[:12]] = limit  # short id, to match ps -a's 12-char ids
    return out


def _cpu_limit_cores(host_config: dict) -> Optional[float]:
    """CPU limit in cores from a container's HostConfig (see parse_inspect_cpu).
    Returns None when no limit is configured."""
    try:
        nano = int(host_config.get("NanoCpus") or 0)
    except (TypeError, ValueError):
        nano = 0
    if nano > 0:
        return nano / 1e9

    try:
        quota = int(host_config.get("CpuQuota") or 0)
    except (TypeError, ValueError):
        quota = 0
    try:
        period = int(host_config.get("CpuPeriod") or 0)
    except (TypeError, ValueError):
        period = 0
    if quota > 0:
        return quota / (period if period > 0 else 100000)
    return None


def parse_inspect_mounts(raw_stdout: str) -> Dict[str, List[str]]:
    """Parse `docker inspect <ids…>` (a JSON array) into a map of container id ->
    the names of its NAMED volumes. Bind mounts are ignored — `docker system df`
    tracks sizes for named/anonymous volumes only. Keyed by both full and short
    id, mirroring parse_inspect_cpu, so this reuses the SAME batched inspect call
    (no extra subprocess). Tolerant: malformed/non-array input -> {}."""
    try:
        data = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, list):
        return {}

    out: Dict[str, List[str]] = {}
    for obj in data:
        if not isinstance(obj, dict):
            continue
        cid = obj.get("Id") or obj.get("ID") or ""
        if not cid:
            continue
        names: List[str] = []
        for mount in obj.get("Mounts") or []:
            if isinstance(mount, dict) and mount.get("Type") == "volume":
                name = mount.get("Name")
                if name:
                    names.append(str(name))
        out[cid] = names
        out[cid[:12]] = names  # short id, to match ps -a's 12-char ids
    return out


def parse_df_verbose_volumes(raw_stdout: str) -> Dict[str, float]:
    """Parse `docker system df -v --format {{json .}}` into {volume_name: bytes}.
    The verbose form is a single JSON object with a `Volumes` array of
    {Name, Size}. Used (cached, off the hot path) to attribute real on-disk
    volume sizes to the containers that mount them. Tolerant: bad/empty input,
    or a daemon that emits the sections as separate objects, degrade to {}."""
    try:
        data = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        return {}

    volumes: list = []
    if isinstance(data, dict):
        volumes = data.get("Volumes") or []
    elif isinstance(data, list):
        for section in data:
            if isinstance(section, dict) and section.get("Volumes"):
                volumes = section["Volumes"]
                break

    out: Dict[str, float] = {}
    for vol in volumes or []:
        if isinstance(vol, dict):
            name = vol.get("Name")
            if name:
                out[str(name)] = parse_size(vol.get("Size"))
    return out


def count_restart_events(raw_stdout: str) -> int:
    """Count container restart events from `docker events --format {{json .}}`.
    The argv already filters to type=container / event=restart, so each parseable
    line is one restart; we still re-check the Action field when present so an
    older daemon that ignores the filter can't inflate the count. Tolerant."""
    count = 0
    for rec in _iter_json_lines(raw_stdout):
        action = str(rec.get("Action") or rec.get("status") or "").lower()
        if not action or "restart" in action:
            count += 1
    return count


def compute_net_rates(
    stats: Dict[str, dict], prev: Dict[str, tuple], now: float
) -> tuple:
    """Aggregate container network throughput as a bytes/sec RATE, derived from
    the delta between two `docker stats` snapshots (docker's NetIO is cumulative
    since container start — there is no per-interval rate in the CLI). Mirrors how
    the host collector derives rates from consecutive SQLite samples.

    Returns (rx_rate, tx_rate, new_prev) where new_prev is the {id: (rx, tx, t)}
    map to store for the next poll. A container seen for the first time, or one
    whose counter went backwards (it restarted -> cumulative resets), contributes
    0 for this interval rather than a bogus spike. Vanished containers drop out
    naturally (new_prev only contains currently-present ones)."""
    rx_rate = 0.0
    tx_rate = 0.0
    new_prev: Dict[str, tuple] = {}
    for entry in _unique_stats(stats):
        cid = entry.get("id") or entry.get("name")
        if not cid:
            continue
        rx = float(entry.get("net_rx", 0.0))
        tx = float(entry.get("net_tx", 0.0))
        new_prev[cid] = (rx, tx, now)
        prior = prev.get(cid)
        if not prior:
            continue
        prx, ptx, pt = prior
        dt = now - pt
        if dt <= 0:
            continue
        if rx >= prx:
            rx_rate += (rx - prx) / dt
        if tx >= ptx:
            tx_rate += (tx - ptx) / dt
    return rx_rate, tx_rate, new_prev


# --------------------------------------------------------------------------- #
# Grouping / aggregation (pure)
# --------------------------------------------------------------------------- #
def group_stacks(
    containers: List[dict],
    stats: Dict[str, dict],
    host_mem_total: int,
    cpu_limits: Optional[Dict[str, Optional[float]]] = None,
    volumes_by_container: Optional[Dict[str, float]] = None,
    host_cores: int = 0,
) -> List[dict]:
    """Join ps containers with their stats and group them into Compose stacks.

    - Containers without a Compose project land in the UNGROUPED bucket.
    - A memory "limit" equal to (≈) host total means no explicit limit was set;
      such a container reports mem.percent = None so the UI hatches its meter.
    - CPU limits come from `cpu_limits` (a container-id -> cores map built by a
      single batched `docker inspect`, see stacks()). A container missing from
      the map (or mapped to None) has no CPU limit set -> cpu.percent = None and
      the UI hatches its meter, mirroring the memory no-limit case.
    - `volumes_by_container` (id -> bytes) attributes real named-volume disk
      usage (from the cached `docker system df -v`) to each container; absent it,
      a container's disk is just its writable layer.
    - Stack health precedence: bad > warn > ok (one stopped container makes the
      whole stack badge bad).
    """
    buckets: Dict[str, List[dict]] = {}
    order: List[str] = []
    for c in containers:
        key = c["project"] or UNGROUPED
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(c)

    stacks: List[dict] = []
    for key in order:
        members = buckets[key]
        vms = [
            _container_vm(
                c, stats, host_mem_total, cpu_limits, volumes_by_container, host_cores
            )
            for c in members
        ]
        stacks.append(_stack_vm(key, vms))
    return stacks


def _container_vm(
    c: dict,
    stats: Dict[str, dict],
    host_mem_total: int,
    cpu_limits: Optional[Dict[str, Optional[float]]] = None,
    volumes_by_container: Optional[Dict[str, float]] = None,
    host_cores: int = 0,
) -> dict:
    """Build the per-container view model (identity, state, mem/cpu/disk)."""
    st = stats.get(c["id"]) or stats.get(c["id"][:12]) or stats.get(c["name"]) or {}

    mem_used = float(st.get("mem_used", 0.0))
    mem_limit = float(st.get("mem_limit", 0.0))
    # Treat a limit within 1% of host RAM (or zero) as "no explicit limit".
    has_mem_limit = bool(mem_limit) and host_mem_total and mem_limit < host_mem_total * 0.99
    mem_percent = (mem_used / mem_limit * 100.0) if has_mem_limit and mem_limit else None
    # Share of the whole host's RAM. The UI fills the meter with this when the
    # container has no explicit limit (so real usage is visible, not hatched).
    mem_host_percent = (mem_used / host_mem_total * 100.0) if host_mem_total else None

    cpu_percent = float(st.get("cpu_percent", 0.0))
    used_cores = cpu_percent / 100.0  # docker CPU%: 100% == one full core
    # Share of all host cores (docker CPU% is already normalized to one core, so
    # divide by core count). The UI's fallback fill when no CPU limit is set.
    cpu_host_percent = (used_cores / host_cores * 100.0) if host_cores else None

    # CPU limit from the batched inspect (None = genuinely unlimited). Look up by
    # full then short id, mirroring the stats lookup above.
    limits = cpu_limits or {}
    cpu_limit_cores = limits.get(c["id"])
    if cpu_limit_cores is None:
        cpu_limit_cores = limits.get(c["id"][:12])
    cpu_util_percent = (
        (used_cores / cpu_limit_cores * 100.0) if cpu_limit_cores else None
    )

    # Real named-volume footprint from the cached `docker system df -v`, joined
    # by the volume names inspect reported for this container. 0 when df -v hasn't
    # been fetched (or the container mounts none), so disk falls back to the
    # writable layer alone — never a crash.
    vols = volumes_by_container or {}
    volumes_bytes = float(vols.get(c["id"]) or vols.get(c["id"][:12]) or 0.0)
    disk_bytes = float(c["rw_bytes"]) + volumes_bytes

    return {
        "id": c["id"],
        "name": c["name"],
        "service": c["service"],
        "image": c["image"],
        "project": c["project"],
        "state": c["state"],
        "state_raw": c["state_raw"],
        "status": c["status"],
        "health": c["health"],
        "mem": {
            "used_bytes": mem_used,
            "limit_bytes": mem_limit if has_mem_limit else None,
            "percent": mem_percent,           # used vs limit; None when unlimited
            "host_percent": mem_host_percent,  # used vs host RAM (fallback fill)
        },
        "cpu": {
            "used_cores": used_cores,
            "used_percent": cpu_percent,
            "limit_cores": cpu_limit_cores,   # None = no CPU limit set
            "percent": cpu_util_percent,      # used vs limit; None when unlimited
            "host_percent": cpu_host_percent,  # used vs all host cores (fallback fill)
        },
        "disk": {
            "bytes": disk_bytes,
            "rw_bytes": float(c["rw_bytes"]),
            "volumes_bytes": volumes_bytes,
            "local_volumes": c["local_volumes"],
        },
    }


def _stack_vm(name: str, containers: List[dict]) -> dict:
    """Roll a stack's containers into name/meta/health + summed mem/cpu/disk."""
    mem_used = sum(c["mem"]["used_bytes"] for c in containers)
    cpu_cores = sum(c["cpu"]["used_cores"] for c in containers)
    disk_bytes = sum(c["disk"]["bytes"] for c in containers)

    stopped = sum(1 for c in containers if c["state"] == "bad")
    warn = sum(1 for c in containers if c["state"] == "warn")
    if stopped:
        health, label = "bad", f"{stopped} stopped"
    elif warn:
        health, label = "warn", f"{warn} unhealthy"
    else:
        health, label = "ok", "Healthy"

    services = [c["service"] for c in containers if c["service"]]
    return {
        "name": name,
        "meta": " · ".join(services),
        "health": health,
        "health_label": label,
        "mem_used_bytes": mem_used,
        "cpu_used_cores": cpu_cores,
        "disk_bytes": disk_bytes,
        "containers": containers,
    }


def build_overview(
    containers: List[dict],
    stats: Dict[str, dict],
    df: Dict[str, dict],
    host_mem_total: int,
    host_cores: int,
    host_disk_total: int,
    net_rx_rate: float = 0.0,
    net_tx_rate: float = 0.0,
    restarts_24h: int = 0,
) -> dict:
    """Aggregate CPU/RAM/disk totals + quick-stat counts across all containers.

    The gauges here are HOST PRESSURE (percent of host cores / RAM / disk), so
    percentages are computed against the host references — unlike the per-
    container meters, which are relative.

    `net_rx_rate`/`net_tx_rate` (bytes/sec) and `restarts_24h` are supplied by the
    caller: they need cross-request state (the previous stats sample) / a separate
    `docker events` query, which live in the I/O layer, not this pure function.
    """
    stacks = group_stacks(containers, stats, host_mem_total, host_cores=host_cores)

    cpu_cores = sum(s.get("cpu_percent", 0.0) for s in _unique_stats(stats)) / 100.0
    mem_used = sum(s.get("mem_used", 0.0) for s in _unique_stats(stats))

    images_bytes = df.get("images", {}).get("size_bytes", 0.0)
    volumes_bytes = df.get("volumes", {}).get("size_bytes", 0.0)
    containers_bytes = df.get("containers", {}).get("size_bytes", 0.0)
    disk_used = images_bytes + volumes_bytes + containers_bytes

    running = sum(1 for c in containers if c["state_raw"].lower() == "running")
    stopped = len(containers) - running
    unhealthy = sum(1 for c in containers if c["health"] == "unhealthy")

    host_cores = host_cores or 1
    return {
        "totals": {
            "cpu": {
                "percent": (cpu_cores / host_cores * 100.0) if host_cores else 0.0,
                "used_cores": cpu_cores,
                "host_cores": host_cores,
            },
            "mem": {
                "percent": (mem_used / host_mem_total * 100.0) if host_mem_total else 0.0,
                "used_bytes": mem_used,
                "total_bytes": host_mem_total,
                # False when the host kernel's memory cgroup is disabled: docker
                # stats then reports MemUsage=0 for every running container (a
                # well-known Raspberry Pi default). The UI uses this to explain
                # the gap instead of showing a misleading 0. Heuristic: running
                # containers always use *some* RAM, so all-zero => accounting off.
                "available": not (running > 0 and mem_used == 0),
            },
            "disk": {
                "percent": (disk_used / host_disk_total * 100.0) if host_disk_total else 0.0,
                "used_bytes": disk_used,
                "total_bytes": host_disk_total,
                "images_bytes": images_bytes,
                "volumes_bytes": volumes_bytes,
                "containers_bytes": containers_bytes,
            },
        },
        "stats": {
            "running": running,
            "stopped": stopped,
            "total": len(containers),
            "stacks": len(stacks),
            "unhealthy": unhealthy,
            # Live throughput as a bytes/sec rate, from the in-memory delta
            # between successive `docker stats` snapshots (see compute_net_rates).
            "net_rx_rate": net_rx_rate,
            "net_tx_rate": net_tx_rate,
            # True count of container restart events in the last 24h, from a
            # cached `docker events` window (see count_restart_events).
            "restarts_24h": restarts_24h,
        },
    }


def _unique_stats(stats: Dict[str, dict]):
    """parse_stats keys each container under several aliases (id/short-id/name);
    iterate each container's stat object exactly once."""
    seen = set()
    for entry in stats.values():
        marker = id(entry)
        if marker in seen:
            continue
        seen.add(marker)
        yield entry


def parse_logs(raw_stdout: str) -> List[dict]:
    """Parse `docker logs --timestamps` output. Each line is
    "<RFC3339 ts> <message>"; we split off the leading timestamp, convert it to
    epoch seconds, and pass the message through untouched. Tolerant: a line with
    no parseable timestamp is kept with ts=None."""
    out: List[dict] = []
    for line in raw_stdout.splitlines():
        if not line:
            continue
        ts, msg = _split_log_line(line)
        out.append({"ts": ts, "message": msg})
    return out


def _split_log_line(line: str) -> tuple:
    """Split a docker --timestamps line into (epoch_seconds|None, message)."""
    parts = line.split(" ", 1)
    stamp = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    ts = _rfc3339_to_epoch(stamp)
    if ts is None:
        return None, line
    return ts, rest


def _rfc3339_to_epoch(stamp: str) -> Optional[int]:
    """Convert docker's RFC3339 nanosecond timestamp to epoch seconds without a
    dependency: '2024-01-02T03:04:05.123456789Z'. Returns None if it doesn't
    look like a timestamp (so plain lines fall through untouched)."""
    if len(stamp) < 20 or stamp[4] != "-" or stamp[10] != "T":
        return None
    import datetime

    s = stamp
    # Python's fromisoformat pre-3.11 can't do 'Z' or nanoseconds; normalize.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Trim fractional seconds to microseconds (6 digits) for fromisoformat.
    m = re.match(r"^(.*\.\d{6})\d*(.*)$", s)
    if m:
        s = m.group(1) + m.group(2)
    try:
        return int(datetime.datetime.fromisoformat(s).timestamp())
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# I/O wrappers (thin)
# --------------------------------------------------------------------------- #
def _run(args: Sequence[str], timeout_seconds: float) -> str:
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DockerError("docker CLI not found on this host") from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerError("docker command timed out") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        msg = detail[-1] if detail else f"docker exited {proc.returncode}"
        raise DockerError(f"docker failed: {msg}")
    return proc.stdout


def _run_logs(args: Sequence[str], timeout_seconds: float) -> str:
    """`docker logs` writes the container's stderr stream to our stderr, so a
    non-zero exit isn't necessarily an error and both streams are log content.
    Merge them and only raise on the hard failures (missing binary / timeout)."""
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DockerError("docker CLI not found on this host") from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerError("docker logs timed out") from exc
    # "No such container" and daemon errors surface on stderr with rc!=0 and no
    # stdout; treat that as an error. Otherwise stderr is legitimate log output.
    if proc.returncode != 0 and not proc.stdout:
        detail = (proc.stderr or "").strip().splitlines()
        msg = detail[-1] if detail else f"docker logs exited {proc.returncode}"
        raise DockerError(f"docker logs failed: {msg}")
    return (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------- #
# In-memory caches (Pi-lightness) + net-rate history
#
# /docker/overview and /docker/stacks are polled together every few seconds. To
# avoid shelling out twice for the same data — and to keep the genuinely slow
# calls (`docker system df -v`, `docker events`) off the hot path — the wrappers
# memoize behind short TTLs. A cache_seconds of 0 disables caching entirely
# (fresh every call): that's the default so unit tests are deterministic and the
# API opts in with real TTLs from config. All state is guarded by one lock.
# --------------------------------------------------------------------------- #
_CACHE_LOCK = threading.Lock()
_snapshot_cache: dict = {"data": None, "at": 0.0}
_df_summary_cache: dict = {"data": None, "at": 0.0}
_df_volumes_cache: dict = {"data": None, "at": 0.0}
_restarts_cache: dict = {"data": None, "at": 0.0}
_net_prev: Dict[str, tuple] = {}


def reset_cache() -> None:
    """Drop every in-memory cache and the net-rate history. Call on config reload
    or from tests to guarantee a cold start."""
    with _CACHE_LOCK:
        _snapshot_cache["data"] = None
        _df_summary_cache["data"] = None
        _df_volumes_cache["data"] = None
        _restarts_cache["data"] = None
        _net_prev.clear()


def _cached(slot: dict, cache_seconds: float, produce):
    """Return slot['data'] if fresher than cache_seconds, else call produce() and
    store it. produce() runs OUTSIDE the lock (it does subprocess I/O); only the
    tiny read/write of the slot is locked. cache_seconds <= 0 bypasses the cache
    (always fresh, nothing stored)."""
    if cache_seconds > 0:
        now = time.monotonic()
        with _CACHE_LOCK:
            if slot["data"] is not None and (now - slot["at"]) < cache_seconds:
                return slot["data"]
    data = produce()
    if cache_seconds > 0:
        with _CACHE_LOCK:
            slot["data"] = data
            slot["at"] = time.monotonic()
    return data


def _get_snapshot(docker_path: str, timeout_seconds: float, cache_seconds: float):
    """The shared (containers, stats) snapshot — `docker ps -a -s` + `docker
    stats`. Memoized so overview and stacks in the same poll cycle don't each run
    the heavy `docker stats`."""
    def produce():
        containers = parse_ps(_run(build_ps_args(docker_path), timeout_seconds))
        stats = parse_stats(_run(build_stats_args(docker_path), timeout_seconds))
        return containers, stats

    return _cached(_snapshot_cache, cache_seconds, produce)


def _get_summary_df(
    docker_path: str, timeout_seconds: float, cache_seconds: float
) -> Dict[str, dict]:
    """The summary `docker system df` (images/volumes/containers totals) for the
    overview disk gauge. It's ~1.5 s on a Pi and changes slowly, so it's cached
    (same TTL as the `-v` variant) to keep it off the every-few-seconds hot path.
    Best-effort: on failure returns {} so the disk gauge reads 0 rather than 5xx."""
    def produce():
        try:
            return parse_system_df(
                _run(build_system_df_args(docker_path), timeout_seconds)
            )
        except DockerError:
            return {}

    return _cached(_df_summary_cache, cache_seconds, produce)


def _net_rates(stats: Dict[str, dict], active: bool) -> tuple:
    """Aggregate net rx/tx rate (bytes/sec) from the delta vs the last poll.
    Requires cross-poll state, so it only runs when caching is active (prod);
    without it (tests) there is no prior sample to diff against -> (0, 0), and no
    module state is touched."""
    if not active:
        return 0.0, 0.0
    now = time.monotonic()
    with _CACHE_LOCK:
        rx, tx, new_prev = compute_net_rates(stats, _net_prev, now)
        _net_prev.clear()
        _net_prev.update(new_prev)
    return rx, tx


def _get_restarts_24h(
    docker_path: str, timeout_seconds: float, cache_seconds: float
) -> int:
    """True count of container restart events in the last 24h via a historical
    `docker events` query. Cached (it changes slowly) and best-effort: any
    failure degrades to 0 rather than breaking /overview."""
    def produce():
        wall = time.time()
        try:
            raw = _run(
                build_events_args(wall - 86400, wall, docker_path), timeout_seconds
            )
        except DockerError:
            return 0
        return count_restart_events(raw)

    return _cached(_restarts_cache, cache_seconds, produce)


def _get_volume_sizes(
    docker_path: str, timeout_seconds: float, cache_seconds: float
) -> Dict[str, float]:
    """{volume_name: bytes} from the slow `docker system df -v`, cached to keep it
    off the hot path. Best-effort: failure -> {} (disk falls back to the writable
    layer only)."""
    def produce():
        try:
            raw = _run(
                build_system_df_args(docker_path, verbose=True), timeout_seconds
            )
        except DockerError:
            return {}
        return parse_df_verbose_volumes(raw)

    return _cached(_df_volumes_cache, cache_seconds, produce)


def _inspect(
    containers: List[dict], docker_path: str, timeout_seconds: float
) -> tuple:
    """One batched `docker inspect` over all container ids, parsed for BOTH the
    per-container CPU limits and the named volumes each mounts (two views of the
    same call — no extra subprocess). Best-effort: any failure degrades to empty
    maps so /docker/stacks still returns (CPU meters hatch, volumes read 0)."""
    ids = [c["id"] for c in containers if c.get("id")]
    if not ids:
        return {}, {}
    try:
        raw = _run(build_inspect_args(ids, docker_path), timeout_seconds)
    except DockerError:
        return {}, {}
    return parse_inspect_cpu(raw), parse_inspect_mounts(raw)


def _container_volume_bytes(
    mounts: Dict[str, List[str]], sizes: Dict[str, float]
) -> Dict[str, float]:
    """Join inspect's per-container volume NAMES with df -v's per-volume SIZES to
    get a container-id -> total-volume-bytes map. A volume missing from df -v
    contributes 0."""
    out: Dict[str, float] = {}
    for cid, names in mounts.items():
        out[cid] = sum(sizes.get(n, 0.0) for n in names)
    return out


def overview(
    docker_path: str = "docker",
    timeout_seconds: float = 8.0,
    *,
    stats_cache_seconds: float = 0.0,
    df_cache_seconds: float = 0.0,
    events_cache_seconds: float = 0.0,
) -> dict:
    """Aggregate host-pressure gauges + quick-stat counts across all containers.

    Hot-path subprocesses: `ps` + `stats` (shared snapshot). The summary `df` is
    now CACHED (df_cache_seconds) — it's ~1.5 s on a Pi and changes slowly, so on
    a cache hit overview costs just the snapshot. Net throughput is a rate from
    the in-memory delta (no extra call); `restarts_24h` comes from a cached
    `docker events` (only re-run on TTL expiry). Net-rate tracking is active only
    when the snapshot is cached."""
    containers, stats = _get_snapshot(docker_path, timeout_seconds, stats_cache_seconds)
    df = _get_summary_df(docker_path, timeout_seconds, df_cache_seconds)
    net_rx_rate, net_tx_rate = _net_rates(stats, active=stats_cache_seconds > 0)
    restarts_24h = _get_restarts_24h(docker_path, timeout_seconds, events_cache_seconds)
    return build_overview(
        containers,
        stats,
        df,
        host_mem_total=_host_mem_total_bytes(),
        host_cores=os.cpu_count() or 1,
        host_disk_total=_host_disk_total_bytes(),
        net_rx_rate=net_rx_rate,
        net_tx_rate=net_tx_rate,
        restarts_24h=restarts_24h,
    )


def stacks(
    docker_path: str = "docker",
    timeout_seconds: float = 8.0,
    *,
    stats_cache_seconds: float = 0.0,
    df_cache_seconds: float = 0.0,
) -> List[dict]:
    """Per-Compose-project stacks with their containers and resource meters.

    Hot path: the shared `ps` + `stats` snapshot + one batched `docker inspect`
    (CPU limits AND volume names in a single call). Real per-container volume
    sizes come from `docker system df -v`, which is CACHED (df_cache_seconds) so
    the slow call stays off the every-few-seconds path — on a cache hit stacks
    costs the same three subprocesses as before."""
    containers, stats = _get_snapshot(docker_path, timeout_seconds, stats_cache_seconds)
    cpu_limits, volume_mounts = _inspect(containers, docker_path, timeout_seconds)
    volume_sizes = _get_volume_sizes(docker_path, timeout_seconds, df_cache_seconds)
    volumes_by_container = _container_volume_bytes(volume_mounts, volume_sizes)
    return group_stacks(
        containers,
        stats,
        _host_mem_total_bytes(),
        cpu_limits,
        volumes_by_container,
        host_cores=os.cpu_count() or 1,
    )


def container_logs(
    container: str,
    *,
    tail: int = 200,
    since: Optional[str] = None,
    docker_path: str = "docker",
    timeout_seconds: float = 8.0,
) -> List[dict]:
    """Live tail for one container, newest at the bottom (docker's natural
    order). The container ref is validated in build_logs_args."""
    args = build_logs_args(
        container,
        tail=tail,
        since=since,
        timestamps=True,
        docker_path=docker_path,
    )
    return parse_logs(_run_logs(args, timeout_seconds))
