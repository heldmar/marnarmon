# Changelog

All notable changes to MarNarMon are recorded here. Versions are git tags
(`vX.Y.Z`); the host engine's `__version__` (surfaced at `/health`) tracks the
tag. Update a deployed server with `sudo ./update.sh` (see the README).

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
