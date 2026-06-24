"""Configuration loading and validation for ServerMon.

Config is a single YAML file (default /etc/servermon/config.yml). The path can
be overridden with the SERVERMON_CONFIG environment variable so the collector,
API and tests can all point at the same place.
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from typing import List

import yaml

DEFAULT_CONFIG_PATH = "/etc/servermon/config.yml"


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

    raw: dict = field(default_factory=dict, repr=False)


def config_path() -> str:
    return os.environ.get("SERVERMON_CONFIG", DEFAULT_CONFIG_PATH)


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

    db_path = database.get("path") or "/var/lib/servermon/metrics.db"

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
        raw=data,
    )
