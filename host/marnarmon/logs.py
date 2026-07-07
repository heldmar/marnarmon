"""Read and filter the systemd journal via journalctl.

Design mirrors collectors.py: pure functions (arg-building, JSON parsing,
priority mapping) are separated from the thin subprocess wrappers that do the
actual I/O, so the tricky parsing/arg logic is unit-testable with fixtures and
no live journal.

Nothing here duplicates log data into MarNarMon's own storage — journald
already indexes, rotates and retains the journal, so we query it live per API
request. This module is only reachable when logs.enabled is true in config and
the service user is a member of the systemd-journal group (granted opt-in by
install.sh); otherwise journalctl returns no data / permission errors.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Dict, List, Optional, Sequence

# --------------------------------------------------------------------------- #
# Priority (syslog severity) mapping
# --------------------------------------------------------------------------- #
# journald PRIORITY is the syslog level 0 (emerg) .. 7 (debug).
_PRIORITY_LABELS = {
    0: "Emergency",
    1: "Alert",
    2: "Critical",
    3: "Error",
    4: "Warning",
    5: "Notice",
    6: "Info",
    7: "Debug",
}

# Coarse bucket used to colour a row in the UI (--good / --warn / --bad).
_PRIORITY_BUCKETS = {
    0: "error",
    1: "error",
    2: "error",
    3: "error",
    4: "warning",
    5: "info",
    6: "info",
    7: "debug",
}

# Friendly severity filter -> journalctl -p threshold. Cumulative ("this level
# or more severe"), matching journalctl's native -p semantics: picking
# "warnings" still shows errors, which is what a troubleshooter expects.
#   errors   -> 0..3 (err and worse)
#   warnings -> 0..4 (warning and worse)
#   info     -> 0..6 (everything except debug)
#   all      -> 0..7 (everything, incl. debug)
_SEVERITY_PRIORITY = {
    "errors": "3",
    "warnings": "4",
    "info": "6",
    "all": None,
}

# Unit name suffixes/patterns that are noise for a human browsing logs.
_SOURCE_DENYLIST_RE = re.compile(
    r"(\.scope|\.mount|\.slice|\.socket|\.device|\.target|\.swap)$"
)

# Synthetic source representing kernel-ring-buffer messages (which have no
# _SYSTEMD_UNIT). Mapped to a _TRANSPORT=kernel match when queried.
KERNEL_SOURCE = "kernel"


class LogsError(RuntimeError):
    """Raised when journalctl cannot be run or fails (missing binary, timeout,
    permission denied). api.py turns this into a friendly HTTP error."""


def priority_label(n: int) -> str:
    return _PRIORITY_LABELS.get(n, "Info")


def priority_bucket(n: int) -> str:
    return _PRIORITY_BUCKETS.get(n, "info")


def friendly_source_label(unit: str) -> str:
    """Turn a raw unit/source into a human label: strip the .service suffix,
    swap separators for spaces, title-case. The raw value is preserved
    separately so the UI can still show/round-trip the exact unit name."""
    if unit == KERNEL_SOURCE:
        return "Kernel"
    name = unit
    for suffix in (".service", ".timer", ".socket"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = name.replace("-", " ").replace("_", " ").replace("@", " ").strip()
    if not name:
        return unit
    # Title-case but leave short all-caps acronyms alone (ssh -> Ssh is fine for
    # a friendly label; keep it simple and predictable).
    return name[:1].upper() + name[1:]


# --------------------------------------------------------------------------- #
# Argument building (pure)
# --------------------------------------------------------------------------- #
def build_args(
    *,
    since_ts: Optional[int] = None,
    until_ts: Optional[int] = None,
    units: Optional[Sequence[str]] = None,
    severity: str = "all",
    keyword: Optional[str] = None,
    limit: int = 100,
    after_cursor: Optional[str] = None,
    journalctl_path: str = "journalctl",
) -> List[str]:
    """Build the journalctl argv for a /logs query. Pure; does no I/O.

    - Newest-first (--reverse) so the freshest lines are at the top.
    - `units` may contain real unit names and/or the literal "kernel"; these are
      OR'd together (multiple values of the same journal field OR automatically;
      the kernel transport is added as a separate match group with '+').
    - `keyword` is treated as a literal substring (re.escape) so a non-expert
      never has to think about regex; journalctl --grep still does the matching.
    - `severity` is a cumulative threshold (see _SEVERITY_PRIORITY).
    """
    args: List[str] = [journalctl_path, "--output=json", "--no-pager", "--reverse"]

    if since_ts is not None:
        args.append(f"--since=@{int(since_ts)}")
    if until_ts is not None:
        args.append(f"--until=@{int(until_ts)}")

    prio = _SEVERITY_PRIORITY.get(severity, None)
    if prio is not None:
        args.append(f"--priority={prio}")

    if keyword:
        # Literal substring match; --grep uses PCRE2 so escape metacharacters.
        args.append(f"--grep={re.escape(keyword)}")
        # Make the literal match case-insensitive for friendlier searching.
        args.append("--case-sensitive=false")

    if after_cursor:
        args.append(f"--after-cursor={after_cursor}")

    args.append(f"--lines={int(limit)}")

    # Field matches go last. Real units OR automatically (same field); the
    # kernel transport is a different field, so join it with journalctl's '+'.
    unit_list = list(units or [])
    real_units = [u for u in unit_list if u and u != KERNEL_SOURCE]
    want_kernel = KERNEL_SOURCE in unit_list

    match_tokens: List[str] = [f"_SYSTEMD_UNIT={u}" for u in real_units]
    if want_kernel:
        if match_tokens:
            match_tokens.append("+")
        match_tokens.append("_TRANSPORT=kernel")
    args.extend(match_tokens)

    return args


# --------------------------------------------------------------------------- #
# Output parsing (pure)
# --------------------------------------------------------------------------- #
def _decode_message(msg) -> str:
    """journalctl emits MESSAGE as a string normally, but as an array of byte
    ints when the payload isn't valid UTF-8. Handle both."""
    if isinstance(msg, list):
        try:
            return bytes(int(b) & 0xFF for b in msg).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            return ""
    if msg is None:
        return ""
    return str(msg)


def _normalize(rec: dict) -> dict:
    try:
        prio = int(rec.get("PRIORITY", 6))
    except (TypeError, ValueError):
        prio = 6
    prio = max(0, min(7, prio))

    try:
        ts_us = int(rec.get("__REALTIME_TIMESTAMP", "0"))
    except (TypeError, ValueError):
        ts_us = 0

    unit = rec.get("_SYSTEMD_UNIT")
    transport = rec.get("_TRANSPORT")
    identifier = rec.get("SYSLOG_IDENTIFIER") or rec.get("_COMM")

    if unit:
        source = unit
    elif transport == "kernel":
        source = KERNEL_SOURCE
    elif identifier:
        source = str(identifier)
    else:
        source = "system"

    return {
        "ts": ts_us // 1_000_000,
        "cursor": rec.get("__CURSOR"),
        "priority": prio,
        "severity": priority_bucket(prio),
        "severity_label": priority_label(prio),
        "unit": unit,
        "source": source,
        "source_label": friendly_source_label(source),
        "identifier": identifier,
        "pid": rec.get("_PID"),
        "hostname": rec.get("_HOSTNAME"),
        "message": _decode_message(rec.get("MESSAGE", "")),
    }


def parse_json_lines(raw_stdout: str) -> List[dict]:
    """Parse journalctl --output=json stdout (one JSON object per line) into
    normalized log dicts. Tolerant: a blank or malformed line is skipped rather
    than failing the whole batch."""
    out: List[dict] = []
    for line in raw_stdout.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        out.append(_normalize(rec))
    return out


def parse_sources(raw_stdout: str) -> List[str]:
    """Parse `journalctl -F _SYSTEMD_UNIT` output (one unit per line) into a
    denoised, sorted list of unit names, dropping transient scope/mount/etc."""
    seen = set()
    for line in raw_stdout.splitlines():
        name = line.strip()
        if not name or name == "-":
            continue
        if _SOURCE_DENYLIST_RE.search(name):
            continue
        seen.add(name)
    return sorted(seen)


# --------------------------------------------------------------------------- #
# I/O wrappers (thin)
# --------------------------------------------------------------------------- #
def _run(args: List[str], timeout_seconds: float) -> str:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LogsError("journalctl not found on this host") from exc
    except subprocess.TimeoutExpired as exc:
        raise LogsError("log query timed out; narrow the time range or filters") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        msg = detail[-1] if detail else f"journalctl exited {proc.returncode}"
        raise LogsError(f"journalctl failed: {msg}")
    return proc.stdout


def query(
    *,
    since_ts: Optional[int] = None,
    until_ts: Optional[int] = None,
    units: Optional[Sequence[str]] = None,
    severity: str = "all",
    keyword: Optional[str] = None,
    limit: int = 100,
    after_cursor: Optional[str] = None,
    journalctl_path: str = "journalctl",
    timeout_seconds: float = 8.0,
) -> List[dict]:
    """Run a filtered journal query and return normalized, newest-first lines."""
    args = build_args(
        since_ts=since_ts,
        until_ts=until_ts,
        units=units,
        severity=severity,
        keyword=keyword,
        limit=limit,
        after_cursor=after_cursor,
        journalctl_path=journalctl_path,
    )
    return parse_json_lines(_run(args, timeout_seconds))


def list_sources(
    journalctl_path: str = "journalctl", timeout_seconds: float = 8.0
) -> List[Dict[str, str]]:
    """Return the selectable log sources: every unit that has ever logged
    (denoised) plus a synthetic 'kernel' source, each with a friendly label and
    the raw value used to filter."""
    args = [journalctl_path, "-F", "_SYSTEMD_UNIT", "--no-pager"]
    units = parse_sources(_run(args, timeout_seconds))
    sources = [{"unit": KERNEL_SOURCE, "label": friendly_source_label(KERNEL_SOURCE)}]
    sources += [{"unit": u, "label": friendly_source_label(u)} for u in units]
    return sources
