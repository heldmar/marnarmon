"""ServerMon host agent: lightweight Linux metrics collector + API.

Reads CPU, RAM, network and disk usage directly from /proc and statvfs
(no psutil), stores rolling history in SQLite, and serves it over a small
FastAPI service. Designed to run on any Linux host (Raspberry Pi, EC2,
Lightsail) via systemd.
"""

__version__ = "0.1.0"
