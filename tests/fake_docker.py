#!/usr/bin/env python3
"""A fake `docker` binary for tests.

Mirrors the fake-`journalctl` harness used to exercise logs.py end-to-end
without a live daemon: this stub is written to a temp dir, marked executable,
and passed as `docker_path=` (or as `docker.path` in a test config) so the
subprocess wrappers in docker.py run for real against canned output.

It recognizes the argv shapes docker.py builds:

    docker stats --no-stream --format {{json .}}
    docker ps -a -s --format {{json .}}
    docker system df [--format {{json .}}]
    docker system df -v --format {{json .}}
    docker inspect -- <id1> <id2> …
    docker logs --tail N [--timestamps] [--since=…] -- <container>

Behavior is tunable through env vars so a single stub can act out the daemon-
unreachable / bad-container / timeout paths the wrappers must handle:

    FAKE_DOCKER_FAIL=1         -> exit 1 with a daemon-error line on stderr
    FAKE_DOCKER_LOGS_RC=1      -> `docker logs` exits 1 (no stdout) => hard error
    FAKE_DOCKER_LOGS_STDERR=1  -> `docker logs` writes to stderr (legit log output)
    FAKE_DOCKER_INSPECT_FAIL=1 -> `docker inspect` exits 1 (stacks() must still
                                  return, with CPU limits degraded to None)
    FAKE_DOCKER_HANG=1         -> sleep well past any test timeout (TimeoutExpired)
"""
import os
import sys
import time

# --- canned fixtures --------------------------------------------------------- #

# One JSON object per line, exactly as `docker stats --format {{json .}}` emits.
# web + db of a Compose project (mem limit set on db), a standalone container
# (no explicit limit -> limit reported == host total), plus a blank + malformed
# line the parser must skip.
STATS = """{"ID":"aaaaaaaaaaaa","Name":"shop_web_1","CPUPerc":"12.50%","MemUsage":"64MiB / 256MiB","MemPerc":"25.00%","NetIO":"1.2kB / 3.4kB","BlockIO":"5MB / 2MB"}
{"ID":"bbbbbbbbbbbb","Name":"shop_db_1","CPUPerc":"3.00%","MemUsage":"128MiB / 512MiB","MemPerc":"25.00%","NetIO":"0B / 0B","BlockIO":"10MB / 0B"}

not-json-at-all
{"ID":"cccccccccccc","Name":"lonely","CPUPerc":"0.00%","MemUsage":"8MiB / 7.6GiB","MemPerc":"0.10%","NetIO":"500B / 100B","BlockIO":"0B / 0B"}
"""

# `docker ps -a -s --format {{json .}}`: two Compose members, one standalone
# running container, and one stopped standalone container.
PS = """{"ID":"aaaaaaaaaaaa","Names":"shop_web_1","Image":"nginx:latest","State":"running","Status":"Up 2 hours (healthy)","Labels":"com.docker.compose.project=shop,com.docker.compose.service=web","Size":"180MB (virtual 600MB)","LocalVolumes":"1"}
{"ID":"bbbbbbbbbbbb","Names":"shop_db_1","Image":"postgres:16","State":"running","Status":"Up 2 hours (unhealthy)","Labels":"com.docker.compose.project=shop,com.docker.compose.service=db","Size":"40MB (virtual 400MB)","LocalVolumes":"2"}
{"ID":"cccccccccccc","Names":"lonely","Image":"redis:7","State":"running","Status":"Up 5 minutes","Labels":"","Size":"0B (virtual 30MB)","LocalVolumes":"0"}
{"ID":"dddddddddddd","Names":"old_worker","Image":"busybox","State":"exited","Status":"Exited (0) 3 days ago","Labels":"","Size":"1.5MB (virtual 5MB)","LocalVolumes":"0"}
"""

# `docker system df --format {{json .}}` (summary): one row per type.
SYSTEM_DF = """{"Type":"Images","TotalCount":"5","Active":"3","Size":"1.2GB","Reclaimable":"400MB (33%)"}
{"Type":"Containers","TotalCount":"4","Active":"3","Size":"220MB","Reclaimable":"1.5MB (0%)"}
{"Type":"Local Volumes","TotalCount":"3","Active":"3","Size":"512MB","Reclaimable":"0B (0%)"}
{"Type":"Build Cache","TotalCount":"10","Active":"0","Size":"64MB","Reclaimable":"64MB"}
"""

# `docker system df -v --format {{json .}}`: verbose form is a single JSON object
# with nested arrays. docker.py doesn't parse this on the hot path; provided so a
# test can prove the -v argv shape is only ever built when explicitly requested.
SYSTEM_DF_V = """{"Images":[{"Repository":"nginx","Tag":"latest","Size":"180MB"}],"Containers":[{"Names":"shop_web_1","Size":"180MB"}],"Volumes":[{"Name":"shop_dbdata","Size":"512MB"}],"BuildCache":[]}
"""

# `docker inspect <ids…>` output: a JSON array (docker returns one array for the
# whole batch). Covers every CPU-limit derivation path parse_inspect_cpu must
# handle: NanoCpus (web, 1.5 cores), CpuQuota/CpuPeriod (db, 0.5 cores),
# CpuQuota with an unset period defaulting to 100000 (old_worker, 2.0 cores), and
# no limit at all (lonely -> None).
INSPECT = """[
  {"Id":"aaaaaaaaaaaa","HostConfig":{"NanoCpus":1500000000,"CpuQuota":0,"CpuPeriod":0}},
  {"Id":"bbbbbbbbbbbb","HostConfig":{"NanoCpus":0,"CpuQuota":50000,"CpuPeriod":100000}},
  {"Id":"cccccccccccc","HostConfig":{"NanoCpus":0,"CpuQuota":0,"CpuPeriod":0}},
  {"Id":"dddddddddddd","HostConfig":{"NanoCpus":0,"CpuQuota":200000,"CpuPeriod":0}}
]
"""

# `docker logs --timestamps` output: RFC3339-nanosecond stamp + message, plus a
# line with no timestamp (must survive with ts=None).
LOGS = """2024-01-02T03:04:05.123456789Z starting up
2024-01-02T03:04:06.000000000Z listening on :80
a line with no timestamp at all
2024-01-02T03:04:07.500000000Z ERROR connection refused
"""


def _emit(text):
    sys.stdout.write(text)


def main(argv):
    if os.environ.get("FAKE_DOCKER_HANG"):
        time.sleep(30)
        return 0

    # Drop the program name.
    args = argv[1:]
    if not args:
        sys.stderr.write("fake-docker: no subcommand\n")
        return 1

    sub = args[0]

    if sub == "logs":
        if os.environ.get("FAKE_DOCKER_LOGS_RC"):
            sys.stderr.write("Error: No such container: nope\n")
            return 1
        if os.environ.get("FAKE_DOCKER_LOGS_STDERR"):
            # Container writes to its stderr; rc may be nonzero but there IS
            # output, so the wrapper must treat it as legit log content.
            sys.stderr.write("2024-01-02T03:04:08.000000000Z warn from stderr\n")
            _emit(LOGS)
            return 0
        _emit(LOGS)
        return 0

    # Every non-logs command honors the daemon-down switch.
    if os.environ.get("FAKE_DOCKER_FAIL"):
        sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock.\n")
        return 1

    if sub == "stats":
        _emit(STATS)
        return 0

    if sub == "ps":
        _emit(PS)
        return 0

    if sub == "inspect":
        if os.environ.get("FAKE_DOCKER_INSPECT_FAIL"):
            sys.stderr.write("Error: inspect failed\n")
            return 1
        _emit(INSPECT)
        return 0

    if sub == "system" and len(args) >= 2 and args[1] == "df":
        if "-v" in args:
            _emit(SYSTEM_DF_V)
        else:
            _emit(SYSTEM_DF)
        return 0

    sys.stderr.write(f"fake-docker: unknown command: {' '.join(args)}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
