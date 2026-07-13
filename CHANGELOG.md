# Changelog

All notable changes to MarNarMon are recorded here. Versions are git tags
(`vX.Y.Z`); the host engine's `__version__` (surfaced at `/health`) tracks the
tag. Update a deployed server with `sudo ./update.sh` (see the README).

## [1.0.6] - 2026-07-13

### Fixed
- **Docker container log drawer now shows newest lines on top.** `docker logs`
  returns oldest→newest and the drawer auto-scrolled to the bottom, so the most
  recent activity sat off-screen. The drawer now lists newest-first and pins to
  the top while streaming, matching the Server Logs view.
- **Docker CLI config warning leaked into the log drawer.** On hosts where
  `~/.docker/config.json` exists but is root-owned (a leftover from an earlier
  `sudo docker …`), the CLI printed `WARNING: Error loading config file: …
  permission denied` to stderr on every call, and the log endpoint (which merges
  a container's stderr into log output) surfaced it as a fake log line. The
  engine now runs every `docker` command with `DOCKER_CONFIG` pointed at its own
  readable directory, so the warning is never emitted — on any host, with no
  per-server file fix required. As a safeguard, docker's own CLI diagnostics are
  also filtered out of container log output.

## [1.0.5] - 2026-07-12

### Fixed
- **Docker CPU still read a frozen `0.00`/near-zero after v1.0.4.** Two causes:
  - *Engine:* the streamed-stats window (2.5 s) ended inside docker's warm-up —
    the daemon's first stats message carries an unreliable CPU delta that the CLI
    reprints for ~2 s before the real value settles. The window now streams 4.5 s
    so the last frame is a live, settled sample.
  - *Dashboard:* per-container and per-stack CPU were shown in **cores**, so a
    container using 0.3% of a core displayed as `0.00 cores`. CPU is now shown as
    a percentage (what `docker stats` reports), with two decimals below 1% so low,
    live usage is visible and moves.

## [1.0.4] - 2026-07-12

### Fixed
- **Docker section reported 0.00% CPU for every container.** The engine polled
  `docker stats --no-stream`, which returns a single daemon sample whose CPU
  delta is computed over ~0 elapsed time — so every container read `0.00%` on
  every server. The engine now streams `docker stats` for a short bounded window
  and reads the last complete refresh frame, which carries a real CPU delta;
  per-frame ANSI/VT100 control codes are stripped during parsing. RAM, disk and
  network readings are unchanged.

### Changed
- `__version__` is now kept in lockstep with the release tag (was stuck at
  `0.1.0`) so `/health` reports the deployed version.

## [1.0.3] - 2026-07-11
- `update.sh`: safe source sync for plain build dirs; never checkout a foreign repo.

## [1.0.2] - 2026-07-11
- `update.sh`: correct Portainer `/data/compose` stack detection.

## [1.0.1] - 2026-07-11
- `update.sh` fixes: accurate `--dry-run`; build-context-aware dashboard update.

## [1.0.0] - 2026-07-11
- First public release: host metrics + Server Logs browser + Docker Monitor.
