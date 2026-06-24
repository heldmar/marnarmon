"""FastAPI service exposing stored metrics.

Endpoints:
  GET /health            - liveness + last-sample age
  GET /metrics/current   - latest snapshot (CPU/RAM/net/load + per-disk)
  GET /metrics/history   - time series; ?minutes=N (default from config)

Optional bearer-token auth: when api.token is set in config, all /metrics and
/health (except the open root) require  Authorization: Bearer <token>.
CORS is open so the dashboard container can call it from a browser.

Run:  uvicorn servermon.api:app --host 0.0.0.0 --port 8787
"""
from __future__ import annotations

import re
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, db
from .config import load_config

cfg = load_config()

app = FastAPI(title="ServerMon", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.get("/")
def root() -> dict:
    return {"service": "servermon", "version": __version__, "host": cfg.host_name}


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
