"""FastAPI service exposing stored metrics and (optionally) the journal.

Endpoints:
  GET /health            - liveness + last-sample age + feature flags
  GET /metrics/current   - latest snapshot (CPU/RAM/net/load + per-disk)
  GET /metrics/history   - time series; ?minutes=N (default from config)
  GET /logs              - filtered systemd-journal lines (when logs enabled)
  GET /logs/sources      - selectable log sources (units + kernel)
  GET /docker/overview   - aggregate container CPU/RAM/disk + counts (when docker enabled)
  GET /docker/stacks     - Compose stacks with per-container meters (when docker enabled)
  GET /docker/logs       - live tail for one container (when docker enabled)

Optional bearer-token auth: when api.token is set in config, all /metrics,
/logs, /docker and /health (except the open root) require
Authorization: Bearer <token>. CORS origins are configurable via
api.allowed_origins (default ["*"]).

The /logs and /docker endpoints are gated by logs.enabled / docker.enabled in
config (default off): they return 503 {"code": ...} when disabled, and the
dashboard uses the `features.logs` / `features.docker` flags on /health to
decide whether to show each section at all.

Run:  uvicorn marnarmon.api:app --host 0.0.0.0 --port 8787
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, db, docker as dockermod, logs as logsmod
from .config import load_config

cfg = load_config()

app = FastAPI(title="MarNarMon", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.allowed_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_WINDOW_RE = re.compile(r"^\s*(\d+)\s*([mhd])\s*$", re.IGNORECASE)


def _open_conn():
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    return conn


def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Enforce bearer token when one is configured; no-op otherwise."""
    if not cfg.api_token:
        return
    expected = f"Bearer {cfg.api_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def _parse_window(window: Optional[str], minutes: Optional[int]) -> int:
    """Resolve a history window to minutes. Accepts ?minutes=N or ?window=24h."""
    if minutes is not None:
        return max(1, minutes)
    if window:
        m = _WINDOW_RE.match(window)
        if not m:
            raise HTTPException(status_code=400, detail="window must look like 30m, 24h, 7d")
        n, unit = int(m.group(1)), m.group(2).lower()
        return n * {"m": 1, "h": 60, "d": 1440}[unit]
    return cfg.default_history_minutes


def _features() -> dict:
    """Capabilities the dashboard adapts to. `logs` gates the whole logs UI;
    `docker` gates the whole Docker Monitor section."""
    return {"logs": cfg.logs_enabled, "docker": cfg.docker_enabled}


@app.get("/")
def root() -> dict:
    return {
        "service": "marnarmon",
        "version": __version__,
        "host": cfg.host_name,
        "features": _features(),
    }


@app.get("/health")
def health(_: None = Depends(require_token)) -> dict:
    conn = _open_conn()
    snap = db.latest_snapshot(conn)
    conn.close()
    now = int(time.time())
    age = (now - snap["ts"]) if snap else None
    # Stale if no sample within ~3 collection intervals.
    healthy = snap is not None and age is not None and age < cfg.interval_minutes * 60 * 3
    return {
        "status": "ok" if healthy else "stale",
        "host": cfg.host_name,
        "last_sample_ts": snap["ts"] if snap else None,
        "last_sample_age_seconds": age,
        "interval_minutes": cfg.interval_minutes,
        "features": _features(),
    }


@app.get("/metrics/current")
def metrics_current(_: None = Depends(require_token)) -> dict:
    conn = _open_conn()
    data = db.current(conn)
    conn.close()
    if data is None:
        raise HTTPException(status_code=503, detail="No metrics collected yet")
    data["host"] = cfg.host_name
    return data


@app.get("/metrics/history")
def metrics_history(
    _: None = Depends(require_token),
    minutes: Optional[int] = Query(default=None, ge=1),
    window: Optional[str] = Query(default=None, description="e.g. 30m, 24h, 7d"),
) -> dict:
    win_minutes = _parse_window(window, minutes)
    since = int(time.time()) - win_minutes * 60
    conn = _open_conn()
    data = db.history(conn, since)
    conn.close()
    data["host"] = cfg.host_name
    data["window_minutes"] = win_minutes
    return data


# --------------------------------------------------------------------------- #
# Server Logs (systemd journal) — opt-in, gated by cfg.logs_enabled
# --------------------------------------------------------------------------- #
_LOGS_DISABLED = {
    "code": "logs_disabled",
    "message": "Server Logs is not enabled on this host.",
}

# Tiny in-process cache for /logs/sources: `journalctl -F` scans the whole
# journal and is comparatively slow, while the set of units rarely changes.
_sources_cache: dict = {"ts": 0.0, "data": None}
_SOURCES_TTL_SECONDS = 60.0


@app.get("/logs")
def logs_query(
    _: None = Depends(require_token),
    q: Optional[str] = Query(default=None, description="keyword (literal substring)"),
    severity: str = Query(default="all", description="errors|warnings|info|all"),
    unit: Optional[List[str]] = Query(default=None, description="source filter, repeatable"),
    window: Optional[str] = Query(default=None, description="e.g. 30m, 24h, 7d"),
    since: Optional[int] = Query(default=None, description="epoch seconds (custom range start)"),
    until: Optional[int] = Query(default=None, description="epoch seconds (custom range end)"),
    limit: Optional[int] = Query(default=None, ge=1),
    after_cursor: Optional[str] = Query(default=None, description="live catch-up cursor"),
    exclude_cursor: Optional[str] = Query(default=None, description="drop this boundary line"),
):
    if not cfg.logs_enabled:
        return JSONResponse(status_code=503, content=_LOGS_DISABLED)

    now = int(time.time())
    if since is not None or until is not None:
        since_ts = since
        until_ts = until
        win_minutes = None
    else:
        win_minutes = _parse_window(window, None) if window else cfg.logs_default_window_minutes
        since_ts = now - win_minutes * 60
        until_ts = None

    lim = min(limit or cfg.logs_default_lines, cfg.logs_max_lines)

    try:
        lines = logsmod.query(
            since_ts=since_ts,
            until_ts=until_ts,
            units=unit,
            severity=severity,
            keyword=q,
            limit=lim,
            after_cursor=after_cursor,
            journalctl_path=cfg.logs_journalctl_path,
            timeout_seconds=cfg.logs_timeout_seconds,
        )
    except logsmod.LogsError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Boundary dedup for "load older": journalctl has no --before-cursor, so the
    # client re-queries with until=<oldest ts shown>; the exact boundary line can
    # reappear (epoch-second granularity is coarser than the journal's µs), so
    # drop it here when the client tells us which cursor it already has.
    if exclude_cursor:
        lines = [ln for ln in lines if ln.get("cursor") != exclude_cursor]

    return {
        "host": cfg.host_name,
        "lines": lines,
        "count": len(lines),
        "truncated": len(lines) >= lim,
        "window_minutes": win_minutes,
    }


@app.get("/logs/sources")
def logs_sources(_: None = Depends(require_token)):
    if not cfg.logs_enabled:
        return JSONResponse(status_code=503, content=_LOGS_DISABLED)

    now = time.time()
    cached = _sources_cache["data"]
    if cached is not None and (now - _sources_cache["ts"]) < _SOURCES_TTL_SECONDS:
        sources = cached
    else:
        try:
            sources = logsmod.list_sources(
                journalctl_path=cfg.logs_journalctl_path,
                timeout_seconds=cfg.logs_timeout_seconds,
            )
        except logsmod.LogsError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        _sources_cache["data"] = sources
        _sources_cache["ts"] = now

    return {"host": cfg.host_name, "sources": sources}


# --------------------------------------------------------------------------- #
# Docker Monitor — opt-in, gated by cfg.docker_enabled
# --------------------------------------------------------------------------- #
_DOCKER_DISABLED = {
    "code": "docker_disabled",
    "message": "Docker Monitor is not enabled on this host.",
}


@app.get("/docker/overview")
def docker_overview(_: None = Depends(require_token)):
    if not cfg.docker_enabled:
        return JSONResponse(status_code=503, content=_DOCKER_DISABLED)

    base = {"host": cfg.host_name, "docker_ok": True, "error": None}
    try:
        data = dockermod.overview(
            docker_path=cfg.docker_path,
            timeout_seconds=cfg.docker_timeout_seconds,
        )
    except dockermod.DockerError as exc:
        # The daemon being unreachable is an expected, recoverable state the
        # dashboard renders as a banner — 200 with docker_ok=false, not a 5xx.
        return {**base, "docker_ok": False, "error": str(exc),
                "totals": None, "stats": None}
    return {**base, **data}


@app.get("/docker/stacks")
def docker_stacks(_: None = Depends(require_token)):
    if not cfg.docker_enabled:
        return JSONResponse(status_code=503, content=_DOCKER_DISABLED)

    base = {"host": cfg.host_name, "docker_ok": True, "error": None}
    try:
        stacks = dockermod.stacks(
            docker_path=cfg.docker_path,
            timeout_seconds=cfg.docker_timeout_seconds,
        )
    except dockermod.DockerError as exc:
        return {**base, "docker_ok": False, "error": str(exc), "stacks": []}
    return {**base, "stacks": stacks}


@app.get("/docker/logs")
def docker_logs(
    _: None = Depends(require_token),
    container: str = Query(..., description="container id or name"),
    tail: Optional[int] = Query(default=None, ge=1, description="lines to tail"),
    since: Optional[str] = Query(default=None, description="epoch seconds or duration (10m, 2h)"),
):
    if not cfg.docker_enabled:
        return JSONResponse(status_code=503, content=_DOCKER_DISABLED)

    lim = min(tail or cfg.docker_logs_default_tail, cfg.docker_logs_max_tail)
    try:
        lines = dockermod.container_logs(
            container,
            tail=lim,
            since=since,
            docker_path=cfg.docker_path,
            timeout_seconds=cfg.docker_timeout_seconds,
        )
    except dockermod.DockerError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "host": cfg.host_name,
        "container": container,
        "lines": lines,
        "count": len(lines),
        "tail": lim,
    }
