"""MarNarMon host agent: lightweight Linux metrics collector + API.

Reads CPU, RAM, network and disk usage directly from /proc and statvfs
(no psutil), stores rolling history in SQLite, and serves it over a small
FastAPI service. Designed to run on any Linux host (Raspberry Pi, EC2,
Lightsail) via systemd.
"""

# Kept in lockstep with the released git tag (vX.Y.Z). The API surfaces it at
# /health and as the FastAPI app version, so bump it in the same commit you tag.
__version__ = "1.0.5"
