"""Configuration loading and validation for MarNarMon.

Config is a single YAML file (default /etc/marnarmon/config.yml). The path can
be overridden with the MARNARMON_CONFIG environment variable so the collector,
API and tests can all point at the same place.
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from typing import List

import yaml

DEFAULT_CONFIG_PATH = "/etc/marnarmon/config.yml"


@dataclass
class Config:
    host_name: str
    interval_minutes: int
    retention_days: int
    db_path: str
    interfaces: List[str]
    disks: List[str]
    api_host: str
    api_port: int
    api_token: str
    default_history_minutes: int
    allowed_origins: List[str]

    # Server Logs (journald browsing). Opt-in: off unless enabled at install.
    logs_enabled: bool
    logs_max_lines: int
    logs_default_lines: int
    logs_default_window_minutes: int
    logs_timeout_seconds: float
    logs_journalctl_path: str

    raw: dict = field(default_factory=dict, repr=False)


def config_path() -> str:
    return os.environ.get("MARNARMON_CONFIG", DEFAULT_CONFIG_PATH)


def load_config(path: str | None = None) -> Config:
    """Load and validate config from YAML. Raises ValueError on bad input."""
    path = path or config_path()
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping, got {type(data).__name__}")

    host = data.get("host", {}) or {}
    collection = data.get("collection", {}) or {}
    database = data.get("database", {}) or {}
    network = data.get("network", {}) or {}
    api = data.get("api", {}) or {}

    host_name = (host.get("name") or "").strip() or socket.gethostname()

    interval = int(collection.get("interval_minutes", 5))
    if interval < 1:
        raise ValueError("collection.interval_minutes must be >= 1")

    retention = int(collection.get("retention_days", 30))
    if retention < 1:
        raise ValueError("collection.retention_days must be >= 1")

    db_path = database.get("path") or "/var/lib/marnarmon/metrics.db"

    interfaces = network.get("interfaces") or []
    if not isinstance(interfaces, list):
        raise ValueError("network.interfaces must be a list")

    disks = data.get("disks") or []
    if not isinstance(disks, list) or not disks:
        raise ValueError("disks must be a non-empty list of mount points")

    api_host = api.get("host") or "0.0.0.0"
    api_port = int(api.get("port", 8787))
    api_token = (api.get("token") or "").strip()
    default_history = int(api.get("default_history_minutes", 1440))

    # CORS: which browser origins may call the API. Default ["*"] (any) is fine
    # behind a trusted proxy/LAN; restrict to the dashboard origin(s) when the
    # API could be reached from untrusted networks.
    allowed = api.get("allowed_origins")
    if allowed is None:
        allowed_origins = ["*"]
    elif isinstance(allowed, list):
        allowed_origins = [str(o) for o in allowed]
    else:
        raise ValueError("api.allowed_origins must be a list of origin strings")

    logs = data.get("logs", {}) or {}
    logs_enabled = bool(logs.get("enabled", False))
    logs_max_lines = int(logs.get("max_lines", 500))
    if logs_max_lines < 1:
        raise ValueError("logs.max_lines must be >= 1")
    logs_default_lines = int(logs.get("default_lines", 100))
    if logs_default_lines < 1:
        raise ValueError("logs.default_lines must be >= 1")
    logs_default_lines = min(logs_default_lines, logs_max_lines)
    logs_default_window_minutes = int(logs.get("default_window_minutes", 60))
    if logs_default_window_minutes < 1:
        raise ValueError("logs.default_window_minutes must be >= 1")
    logs_timeout_seconds = float(logs.get("timeout_seconds", 8.0))
    if logs_timeout_seconds <= 0:
        raise ValueError("logs.timeout_seconds must be > 0")
    logs_journalctl_path = str(logs.get("journalctl_path") or "journalctl")

    return Config(
        host_name=host_name,
        interval_minutes=interval,
        retention_days=retention,
        db_path=db_path,
        interfaces=[str(i) for i in interfaces],
        disks=[str(d) for d in disks],
        api_host=api_host,
        api_port=api_port,
        api_token=api_token,
        default_history_minutes=default_history,
        allowed_origins=allowed_origins,
        logs_enabled=logs_enabled,
        logs_max_lines=logs_max_lines,
        logs_default_lines=logs_default_lines,
        logs_default_window_minutes=logs_default_window_minutes,
        logs_timeout_seconds=logs_timeout_seconds,
        logs_journalctl_path=logs_journalctl_path,
        raw=data,
    )
