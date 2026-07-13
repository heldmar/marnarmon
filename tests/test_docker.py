"""Unit + API tests for the Docker Monitor (docker.py + /docker/* endpoints).

Fixture-based, mirroring test_logs.py: everything tricky (size/percent parsing,
JSON-lines parsing, stack grouping, aggregation, argv building + the security
whitelist) is a pure function tested with canned strings, and the thin
subprocess wrappers are exercised end-to-end against a **fake `docker` binary**
(tests/fake_docker.py) — the same trick the logs phase used with fake
`journalctl`, so no live daemon is needed.

Run:

    cd host && .venv/bin/python -m pytest ../tests -q
    # or, without pytest:
    python ../tests/test_docker.py

The API tests need FastAPI's TestClient (httpx) — test-only tooling, not a new
project runtime dependency. They are skipped gracefully if unavailable.
"""
import os
import stat
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host"))

from marnarmon import docker as D  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_DOCKER_SRC = os.path.join(HERE, "fake_docker.py")


# --------------------------------------------------------------------------- #
# Tiny harness (same reporting style as test_logs.py) so the file runs both
# under pytest and as a bare `python tests/test_docker.py`.
# --------------------------------------------------------------------------- #
def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        raise AssertionError(name)


def _fake_docker_path(tmpdir):
    """Write an executable `docker` shim and return its path.

    It's a tiny /bin/sh wrapper that execs the current interpreter on
    fake_docker.py, forwarding argv. A `/bin/sh` wrapper (rather than a shebang
    copy) is deliberate: the interpreter path can contain spaces (this repo dir
    does), which a `#!` line cannot express but shell quoting can.
    """
    shim = os.path.join(tmpdir, "docker")
    with open(shim, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n")
        fh.write(f'exec "{sys.executable}" "{FAKE_DOCKER_SRC}" "$@"\n')
    os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


# --------------------------------------------------------------------------- #
# Size / percent parsing
# --------------------------------------------------------------------------- #
def test_parse_size():
    check("bytes plain", D.parse_size("512B") == 512)
    check("no unit == bytes", D.parse_size("1024") == 1024)
    check("SI MB (1000^2)", D.parse_size("180MB") == 180 * 1000 ** 2)
    check("binary MiB (1024^2)", D.parse_size("5.5MiB") == 5.5 * 1024 ** 2)
    check("GiB", D.parse_size("1.9GiB") == 1.9 * 1024 ** 3)
    check("GB", D.parse_size("1.2GB") == 1.2 * 1000 ** 3)
    check("zero", D.parse_size("0B") == 0.0)
    check("whitespace tolerated", D.parse_size("  64 MiB  ") == 64 * 1024 ** 2)
    # Tolerance: never raise on junk.
    check("None -> 0", D.parse_size(None) == 0.0)
    check("empty -> 0", D.parse_size("") == 0.0)
    check("garbage -> 0", D.parse_size("N/A") == 0.0)
    check("unknown unit -> value*1", D.parse_size("5zz") == 5.0)


def test_parse_size_pair():
    a, b = D.parse_size_pair("5.5MiB / 1.9GiB")
    check("pair a", a == 5.5 * 1024 ** 2)
    check("pair b", b == 1.9 * 1024 ** 3)
    r, t = D.parse_size_pair("1.2kB / 3.4kB")
    check("netio rx", r == 1.2 * 1000)
    check("netio tx", t == 3.4 * 1000)
    # Missing second half degrades to 0, doesn't raise.
    x, y = D.parse_size_pair("42MB")
    check("single -> b=0", x == 42 * 1000 ** 2 and y == 0.0)
    n0, n1 = D.parse_size_pair(None)
    check("None pair -> (0,0)", n0 == 0.0 and n1 == 0.0)


def test_parse_percent():
    check("basic", D.parse_percent("12.50%") == 12.5)
    check("zero", D.parse_percent("0.00%") == 0.0)
    check("no sign", D.parse_percent("3") == 3.0)
    check("None -> 0", D.parse_percent(None) == 0.0)
    check("garbage -> 0", D.parse_percent("--") == 0.0)


# --------------------------------------------------------------------------- #
# State / health classification
# --------------------------------------------------------------------------- #
def test_health_label():
    check("healthy", D.health_label("Up 2 hours (healthy)") == "healthy")
    check("unhealthy", D.health_label("Up 2 hours (unhealthy)") == "unhealthy")
    check("starting", D.health_label("Up 5s (health: starting)") == "starting")
    check("none when no healthcheck", D.health_label("Up 5 minutes") is None)
    check("none on empty", D.health_label("") is None)
    check("none on None", D.health_label(None) is None)


def test_classify_state():
    check("running+healthy -> ok", D.classify_state("running", "Up 2h (healthy)") == "ok")
    check("running no health -> ok", D.classify_state("running", "Up 5m") == "ok")
    check("running+unhealthy -> warn", D.classify_state("running", "Up 2h (unhealthy)") == "warn")
    check("restarting -> warn", D.classify_state("restarting", "Restarting (1) 2s ago") == "warn")
    check("paused -> warn", D.classify_state("paused", "Up 2h (Paused)") == "warn")
    check("exited -> bad", D.classify_state("exited", "Exited (0) 3 days ago") == "bad")
    check("created -> bad", D.classify_state("created", "Created") == "bad")
    check("dead -> bad", D.classify_state("dead", "Dead") == "bad")
    check("unknown -> bad", D.classify_state("", "") == "bad")
    check("case-insensitive state", D.classify_state("RUNNING", "Up 1h") == "ok")


# --------------------------------------------------------------------------- #
# Argument building — including the security whitelist (critical)
# --------------------------------------------------------------------------- #
def test_build_simple_args():
    # Streamed (NOT --no-stream): --no-stream reports 0% CPU for every container.
    check("stats streamed json", D.build_stats_args("docker") ==
          ["docker", "stats", "--format", "{{json .}}"])
    check("ps -a -s json", D.build_ps_args("docker") ==
          ["docker", "ps", "-a", "-s", "--format", "{{json .}}"])
    # Cheap summary df must NOT carry -v.
    df = D.build_system_df_args("docker")
    check("df summary is cheap (no -v)", "-v" not in df)
    check("df summary shape", df == ["docker", "system", "df", "--format", "{{json .}}"])
    # -v only when explicitly asked.
    dfv = D.build_system_df_args("docker", verbose=True)
    check("df verbose has -v", "-v" in dfv)
    check("df verbose position after df", dfv.index("-v") == dfv.index("df") + 1)
    # Custom docker path is honored (config docker.path override).
    check("custom path", D.build_stats_args("/usr/bin/docker")[0] == "/usr/bin/docker")


def test_build_logs_args_ok():
    a = D.build_logs_args("shop_web_1", tail=200, since=None, timestamps=True)
    check("argv is a list", isinstance(a, list))
    check("has tail", "--tail" in a and "200" in a)
    check("has timestamps", "--timestamps" in a)
    check("has -- separator", "--" in a)
    # The container ref must come AFTER the -- separator (option-injection guard).
    check("container after --", a.index("shop_web_1") > a.index("--"))
    check("container is last", a[-1] == "shop_web_1")
    # timestamps off omits the flag.
    b = D.build_logs_args("x", timestamps=False)
    check("no timestamps flag", "--timestamps" not in b)
    # tail is coerced to int (a float/str can't slip a shell token in).
    c = D.build_logs_args("x", tail="500")
    check("tail coerced to str-int", "500" in c)


def test_since_whitelist():
    ok = ["10m", "2h", "1h30m", "30s", "1700000000", "0"]
    for v in ok:
        a = D.build_logs_args("web", since=v)
        check(f"since {v} accepted", f"--since={v}" in a)
    # NB: an empty string is not "rejected" — build_logs_args treats a falsy
    # since as "no --since filter" (a legitimate no-op), so it's excluded here.
    bad = ["10m; rm -rf /", "$(whoami)", "10 m", "-1", "yesterday", "10d", "10m ", "'10m'"]
    for v in bad:
        try:
            D.build_logs_args("web", since=v)
            check(f"since {v!r} REJECTED", False)
        except D.DockerError:
            check(f"since {v!r} rejected", True)


def test_container_whitelist_rejects_injection():
    """The container ref whitelist is the primary command-injection guard."""
    good = ["shop_web_1", "abc123", "my.container-1", "a" * 128,
            "ABCdef0123456789", "x"]
    for c in good:
        check(f"container {c!r} accepted", D.build_logs_args(c)[-1] == c)

    evil = [
        "; rm -rf /",          # command separator
        "$(reboot)",           # command substitution
        "`id`",                # backtick substitution
        "--since=10m",         # option-looking value
        "-f",                  # leading-dash flag
        "--rm",                # destructive flag shape
        "web container",       # embedded space
        "web\ttab",            # embedded tab
        "web\nnewline",        # embedded newline
        "web&&whoami",         # shell AND
        "web|cat",             # pipe
        "web>out",             # redirect
        "a" * 129,             # over length cap
        "",                    # empty
        "_leading_underscore",  # first char must be alnum
        ".dotfirst",           # first char must be alnum
        "-leadingdash",        # leading dash
    ]
    for c in evil:
        try:
            D.build_logs_args(c)
            check(f"container {c!r} REJECTED", False)
        except D.DockerError:
            check(f"container {c!r} rejected", True)


def test_build_inspect_args():
    """One batched inspect argv for all ids — never one call per container."""
    a = D.build_inspect_args(["aaaaaaaaaaaa", "bbbbbbbbbbbb"], "docker")
    check("single inspect call", a[:3] == ["docker", "inspect", "--"])
    check("all ids in one argv", a[3:] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    check("ids after -- separator", a.index("aaaaaaaaaaaa") > a.index("--"))
    # Empty / falsy ids -> no call at all (caller skips).
    check("empty ids -> []", D.build_inspect_args([]) == [])
    check("None ids -> []", D.build_inspect_args(None) == [])
    check("all-falsy ids -> []", D.build_inspect_args(["", None]) == [])
    # Custom docker path honored.
    check("custom path", D.build_inspect_args(["abc123"], "/usr/bin/docker")[0] == "/usr/bin/docker")
    # The SAME whitelist as build_logs_args guards each id.
    evil = ["; rm -rf /", "$(reboot)", "`id`", "--rm", "-f", "a b", "a\nb", "a" * 129]
    for cid in evil:
        try:
            D.build_inspect_args(["aaaaaaaaaaaa", cid])
            check(f"inspect id {cid!r} REJECTED", False)
        except D.DockerError:
            check(f"inspect id {cid!r} rejected", True)


# --------------------------------------------------------------------------- #
# Output parsing
# --------------------------------------------------------------------------- #
STATS = """{"ID":"aaaaaaaaaaaa","Name":"shop_web_1","CPUPerc":"12.50%","MemUsage":"64MiB / 256MiB","MemPerc":"25.00%","NetIO":"1.2kB / 3.4kB","BlockIO":"5MB / 2MB"}

not json here
{"ID":"bbbbbbbbbbbb","Name":"shop_db_1","CPUPerc":"3.00%","MemUsage":"128MiB / 512MiB","MemPerc":"25.00%","NetIO":"0B / 0B","BlockIO":"10MB / 0B"}
"""

PS = """{"ID":"aaaaaaaaaaaa","Names":"shop_web_1","Image":"nginx:latest","State":"running","Status":"Up 2 hours (healthy)","Labels":"com.docker.compose.project=shop,com.docker.compose.service=web","Size":"180MB (virtual 600MB)","LocalVolumes":"1"}
{"ID":"bbbbbbbbbbbb","Names":"shop_db_1","Image":"postgres:16","State":"running","Status":"Up 2 hours (unhealthy)","Labels":"com.docker.compose.project=shop,com.docker.compose.service=db","Size":"40MB (virtual 400MB)","LocalVolumes":"2"}
{"ID":"cccccccccccc","Names":"lonely","Image":"redis:7","State":"running","Status":"Up 5 minutes","Labels":"","Size":"0B (virtual 30MB)","LocalVolumes":"0"}
{"ID":"dddddddddddd","Names":"old_worker","Image":"busybox","State":"exited","Status":"Exited (0) 3 days ago","Labels":"","Size":"1.5MB (virtual 5MB)","LocalVolumes":"bad"}
"""

SYSTEM_DF = """{"Type":"Images","Size":"1.2GB","Reclaimable":"400MB (33%)"}
{"Type":"Containers","Size":"220MB","Reclaimable":"1.5MB (0%)"}
{"Type":"Local Volumes","Size":"512MB","Reclaimable":"0B (0%)"}
{"Type":"Build Cache","Size":"64MB","Reclaimable":"64MB"}
{"Type":"Something New From v99","Size":"9GB","Reclaimable":"0B"}
"""


def test_parse_stats():
    s = D.parse_stats(STATS)
    web = s["aaaaaaaaaaaa"]
    check("stats keyed by full id", web["name"] == "shop_web_1")
    check("stats keyed by short id", s["aaaaaaaaaaaa"[:12]] is web)
    check("stats keyed by name", s["shop_web_1"] is web)
    check("cpu parsed", web["cpu_percent"] == 12.5)
    check("mem_used bytes", web["mem_used"] == 64 * 1024 ** 2)
    check("mem_limit bytes", web["mem_limit"] == 256 * 1024 ** 2)
    check("net_rx", web["net_rx"] == 1.2 * 1000)
    check("block_read", web["block_read"] == 5 * 1000 ** 2)
    # Malformed + blank lines skipped: exactly 2 containers survived.
    check("2 unique containers", len(list(D._unique_stats(s))) == 2)


def test_parse_stats_streamed_frames():
    """Streamed `docker stats` output: each refresh frame is led by a cursor-home
    (ESC[H) and every line trails an erase-line (ESC[K). parse_stats must strip
    the control codes and read the LAST COMPLETE frame — so the fresh per-frame
    CPU delta wins, not the stale first frame (this is the whole point of
    streaming instead of --no-stream, which reads 0% for everyone)."""
    H, K, J = "\x1b[H", "\x1b[K", "\x1b[J"
    def frame(cpu_web, cpu_db):
        return (
            H + '{"ID":"aaaaaaaaaaaa","Name":"shop_web_1","CPUPerc":"%s",'
            '"MemUsage":"64MiB / 256MiB","MemPerc":"25.00%%","NetIO":"1.2kB / 3.4kB",'
            '"BlockIO":"5MB / 2MB"}' % cpu_web + K + "\n"
            '{"ID":"bbbbbbbbbbbb","Name":"shop_db_1","CPUPerc":"%s",'
            '"MemUsage":"128MiB / 512MiB","MemPerc":"25.00%%","NetIO":"0B / 0B",'
            '"BlockIO":"10MB / 0B"}' % cpu_db + K + "\n" + K + "\n" + J
        )
    # First frame reads 0% (the --no-stream symptom); later frames have real deltas.
    streamed = frame("0.00%", "0.00%") + frame("12.50%", "3.00%")
    s = D.parse_stats(streamed)
    check("streamed: last frame wins for web", s["shop_web_1"]["cpu_percent"] == 12.5)
    check("streamed: last frame wins for db", s["shop_db_1"]["cpu_percent"] == 3.0)
    check("streamed: no ANSI leaks into id", s["aaaaaaaaaaaa"]["name"] == "shop_web_1")
    check("streamed: 2 unique containers", len(list(D._unique_stats(s))) == 2)
    # A truncated trailing frame (stream cut mid-write) is dropped for the prior
    # complete one, so no container is lost and values stay real.
    truncated = frame("12.50%", "3.00%") + H + \
        '{"ID":"aaaaaaaaaaaa","Name":"shop_web_1","CPUPerc":"99'  # torn line
    s2 = D.parse_stats(truncated)
    check("truncated: falls back to full frame", s2["shop_web_1"]["cpu_percent"] == 12.5)
    check("truncated: db still present", "shop_db_1" in s2)


def test_parse_ps():
    rows = D.parse_ps(PS)
    check("4 rows", len(rows) == 4)
    web = rows[0]
    check("project label", web["project"] == "shop")
    check("service label", web["service"] == "web")
    check("state classified ok", web["state"] == "ok")
    check("health healthy", web["health"] == "healthy")
    check("rw bytes from size", web["rw_bytes"] == 180 * 1000 ** 2)
    check("virtual bytes parsed", web["virtual_bytes"] == 600 * 1000 ** 2)
    check("local_volumes int", web["local_volumes"] == 1)

    db = rows[1]
    check("db unhealthy -> warn", db["state"] == "warn")

    lonely = rows[2]
    check("no project label -> empty", lonely["project"] == "")
    check("service falls back to name", lonely["service"] == "lonely")

    worker = rows[3]
    check("exited -> bad", worker["state"] == "bad")
    check("bad LocalVolumes -> 0", worker["local_volumes"] == 0)


def test_parse_system_df():
    df = D.parse_system_df(SYSTEM_DF)
    check("images size", df["images"]["size_bytes"] == 1.2 * 1000 ** 3)
    check("containers size", df["containers"]["size_bytes"] == 220 * 1000 ** 2)
    check("volumes normalized key", df["volumes"]["size_bytes"] == 512 * 1000 ** 2)
    check("build_cache key", df["build_cache"]["size_bytes"] == 64 * 1000 ** 2)
    check("reclaimable stripped of percent", df["images"]["reclaimable_bytes"] == 400 * 1000 ** 2)
    # Unknown future Type is ignored, not fatal (forward-compat).
    check("unknown type ignored", "something new from v99" not in df)


INSPECT = """[
  {"Id":"aaaaaaaaaaaa","HostConfig":{"NanoCpus":1500000000,"CpuQuota":0,"CpuPeriod":0}},
  {"Id":"bbbbbbbbbbbb","HostConfig":{"NanoCpus":0,"CpuQuota":50000,"CpuPeriod":100000}},
  {"Id":"dddddddddddd","HostConfig":{"NanoCpus":0,"CpuQuota":200000,"CpuPeriod":0}},
  {"Id":"cccccccccccc","HostConfig":{"NanoCpus":0,"CpuQuota":0,"CpuPeriod":0}}
]
"""


def test_parse_inspect_cpu():
    m = D.parse_inspect_cpu(INSPECT)
    # NanoCpus wins: 1.5e9 / 1e9 = 1.5 cores.
    check("NanoCpus -> cores", abs(m["aaaaaaaaaaaa"] - 1.5) < 1e-9)
    # CpuQuota / CpuPeriod = 50000/100000 = 0.5 cores.
    check("quota/period -> cores", abs(m["bbbbbbbbbbbb"] - 0.5) < 1e-9)
    # CpuQuota set but CpuPeriod unset -> default period 100000: 200000/100000 = 2.0.
    check("quota with default period", abs(m["dddddddddddd"] - 2.0) < 1e-9)
    # No limit at all -> genuinely unlimited -> None.
    check("no limit -> None", m["cccccccccccc"] is None)
    # Keyed by both full and short id (short == full here, both present).
    check("short-id key present", "aaaaaaaaaaaa"[:12] in m)


def test_parse_inspect_cpu_tolerant():
    check("malformed json -> {}", D.parse_inspect_cpu("not json") == {})
    check("empty -> {}", D.parse_inspect_cpu("") == {})
    check("non-array -> {}", D.parse_inspect_cpu('{"Id":"x"}') == {})
    # Missing HostConfig / fields degrade to None, never raise.
    m = D.parse_inspect_cpu('[{"Id":"zzzzzzzzzzzz"},{"Id":"yyyyyyyyyyyy","HostConfig":{}}]')
    check("missing HostConfig -> None", m["zzzzzzzzzzzz"] is None)
    check("empty HostConfig -> None", m["yyyyyyyyyyyy"] is None)
    # Junk numeric fields tolerated.
    m2 = D.parse_inspect_cpu('[{"Id":"q","HostConfig":{"NanoCpus":"oops","CpuQuota":null,"CpuPeriod":"x"}}]')
    check("junk numerics -> None", m2["q"] is None)
    # An entry without an Id is skipped, not fatal.
    m3 = D.parse_inspect_cpu('[{"HostConfig":{"NanoCpus":1000000000}}]')
    check("no-Id entry skipped", m3 == {})


def test_container_cpu_limit_from_inspect():
    """With a cpu_limits map, the container VM reports a real limit + percent;
    without one (or mapped to None) it stays no-limit (percent None)."""
    containers = D.parse_ps(PS)
    stats = D.parse_stats(STATS)
    limits = D.parse_inspect_cpu(INSPECT)

    # web: used 12.5% -> 0.125 cores, limit 1.5 cores -> 8.333% util.
    web = D._container_vm(
        next(c for c in containers if c["name"] == "shop_web_1"), stats, HOST_MEM, limits
    )
    check("cpu limit_cores set", abs(web["cpu"]["limit_cores"] - 1.5) < 1e-9)
    check("cpu used_cores preserved", abs(web["cpu"]["used_cores"] - 0.125) < 1e-9)
    check("cpu percent = used/limit", abs(web["cpu"]["percent"] - (0.125 / 1.5 * 100)) < 1e-6)

    # lonely: no CPU limit -> limit_cores None, percent None (hatched meter).
    lonely = D._container_vm(
        next(c for c in containers if c["name"] == "lonely"), stats, HOST_MEM, limits
    )
    check("unlimited -> limit None", lonely["cpu"]["limit_cores"] is None)
    check("unlimited -> percent None", lonely["cpu"]["percent"] is None)

    # No map at all -> falls back to no-limit (backward compatible).
    web_nolimits = D._container_vm(
        next(c for c in containers if c["name"] == "shop_web_1"), stats, HOST_MEM
    )
    check("no map -> limit None", web_nolimits["cpu"]["limit_cores"] is None)
    check("no map -> percent None", web_nolimits["cpu"]["percent"] is None)


def test_parse_ps_empty_and_malformed():
    check("empty ps -> []", D.parse_ps("") == [])
    check("empty stats -> {}", D.parse_stats("") == {})
    check("all-garbage ps -> []", D.parse_ps("nope\n{bad\n") == [])
    check("empty df -> {}", D.parse_system_df("") == {})


# --------------------------------------------------------------------------- #
# Grouping / aggregation
# --------------------------------------------------------------------------- #
HOST_MEM = 8 * 1024 ** 3  # 8 GiB host


def test_group_stacks():
    containers = D.parse_ps(PS)
    stats = D.parse_stats(STATS)
    stacks = D.group_stacks(containers, stats, HOST_MEM)

    names = [s["name"] for s in stacks]
    check("shop stack present", "shop" in names)
    check("ungrouped bucket present", D.UNGROUPED in names)

    shop = next(s for s in stacks if s["name"] == "shop")
    check("shop has 2 members", len(shop["containers"]) == 2)
    # db is unhealthy(warn), web ok -> stack warn.
    check("stack health warn from unhealthy", shop["health"] == "warn")
    check("stack meta lists services", "web" in shop["meta"] and "db" in shop["meta"])

    ung = next(s for s in stacks if s["name"] == D.UNGROUPED)
    # lonely(running) + old_worker(exited) -> one stopped -> bad.
    check("ungrouped has 2", len(ung["containers"]) == 2)
    check("stack bad from stopped", ung["health"] == "bad")
    check("stack bad label counts stopped", ung["health_label"] == "1 stopped")


def test_mem_limit_semantics():
    """A limit ~= host RAM means 'no explicit limit' -> percent None; a real
    sub-host limit yields a real percent."""
    containers = D.parse_ps(PS)
    # 'lonely' stats report an 8GiB-ish limit == host total -> no limit.
    stats = D.parse_stats(
        '{"ID":"cccccccccccc","Name":"lonely","CPUPerc":"1.0%",'
        '"MemUsage":"8MiB / 8GiB","MemPerc":"0.1%","NetIO":"0B / 0B","BlockIO":"0B / 0B"}\n'
    )
    vm = D._container_vm(
        next(c for c in containers if c["name"] == "lonely"), stats, HOST_MEM
    )
    check("no-limit -> limit_bytes None", vm["mem"]["limit_bytes"] is None)
    check("no-limit -> percent None", vm["mem"]["percent"] is None)

    # web has a real 256MiB limit under the 8GiB host.
    vm2 = D._container_vm(
        next(c for c in containers if c["name"] == "shop_web_1"),
        D.parse_stats(STATS), HOST_MEM,
    )
    check("real limit set", vm2["mem"]["limit_bytes"] == 256 * 1024 ** 2)
    check("real percent computed", abs(vm2["mem"]["percent"] - 25.0) < 1e-6)
    # cpu.percent is always None (no per-container CPU limit without inspect).
    check("cpu percent None by design", vm2["cpu"]["percent"] is None)
    check("cpu used_cores from %", abs(vm2["cpu"]["used_cores"] - 0.125) < 1e-9)


def test_group_stacks_empty():
    check("no containers -> no stacks", D.group_stacks([], {}, HOST_MEM) == [])


def test_build_overview():
    containers = D.parse_ps(PS)
    stats = D.parse_stats(STATS)
    df = D.parse_system_df(SYSTEM_DF)
    ov = D.build_overview(
        containers, stats, df,
        host_mem_total=HOST_MEM, host_cores=4, host_disk_total=100 * 1000 ** 3,
    )
    st = ov["stats"]
    check("running count", st["running"] == 3)
    check("stopped count", st["stopped"] == 1)
    check("total count", st["total"] == 4)
    check("unhealthy count", st["unhealthy"] == 1)
    check("stacks count (shop + ungrouped)", st["stacks"] == 2)

    tot = ov["totals"]
    # cpu cores = (12.5 + 3.0)/100 = 0.155 over 4 host cores.
    check("cpu used_cores summed", abs(tot["cpu"]["used_cores"] - 0.155) < 1e-9)
    check("cpu percent of host", abs(tot["cpu"]["percent"] - (0.155 / 4 * 100)) < 1e-6)
    # mem = 64MiB + 128MiB.
    check("mem used summed", tot["mem"]["used_bytes"] == (64 + 128) * 1024 ** 2)
    # disk = images + volumes + containers from df.
    expect_disk = (1.2 * 1000 ** 3) + (512 * 1000 ** 2) + (220 * 1000 ** 2)
    check("disk used from df", abs(tot["disk"]["used_bytes"] - expect_disk) < 1)
    check("disk images broken out", tot["disk"]["images_bytes"] == 1.2 * 1000 ** 3)


def test_build_overview_empty():
    ov = D.build_overview([], {}, {}, host_mem_total=HOST_MEM, host_cores=4,
                          host_disk_total=100 * 1000 ** 3)
    check("empty totals cpu 0", ov["totals"]["cpu"]["used_cores"] == 0.0)
    check("empty stats total 0", ov["stats"]["total"] == 0)
    check("empty no divide-by-zero", ov["totals"]["mem"]["percent"] == 0.0)


# --------------------------------------------------------------------------- #
# Log parsing
# --------------------------------------------------------------------------- #
LOGS = """2024-01-02T03:04:05.123456789Z starting up
2024-01-02T03:04:06.000000000Z listening on :80
a line with no timestamp at all
2024-01-02T03:04:07.500000000Z ERROR connection refused
"""


def test_parse_logs():
    out = D.parse_logs(LOGS)
    check("4 lines", len(out) == 4)
    check("ts parsed to epoch", out[0]["ts"] == 1704164645)
    check("message split off ts", out[0]["message"] == "starting up")
    # A line with no parseable timestamp is kept with ts=None and full text.
    check("no-ts line ts None", out[2]["ts"] is None)
    check("no-ts line message intact", out[2]["message"] == "a line with no timestamp at all")
    check("empty -> []", D.parse_logs("") == [])


# --------------------------------------------------------------------------- #
# End-to-end via the fake `docker` binary (subprocess wrappers)
# --------------------------------------------------------------------------- #
def test_wrappers_end_to_end(tmp_path=None):
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)

    ov = D.overview(docker_path=docker, timeout_seconds=8.0)
    check("overview totals present", "totals" in ov and "stats" in ov)
    check("overview counts running", ov["stats"]["running"] == 3)

    stacks = D.stacks(docker_path=docker, timeout_seconds=8.0)
    check("stacks returned", len(stacks) == 2)
    # The batched inspect populated per-container CPU limits end-to-end.
    shop = next(s for s in stacks if s["name"] == "shop")
    web = next(c for c in shop["containers"] if c["name"] == "shop_web_1")
    check("e2e web cpu limit 1.5 cores", abs(web["cpu"]["limit_cores"] - 1.5) < 1e-9)
    check("e2e web cpu percent set", web["cpu"]["percent"] is not None)
    ung = next(s for s in stacks if s["name"] == D.UNGROUPED)
    lonely = next(c for c in ung["containers"] if c["name"] == "lonely")
    check("e2e lonely cpu unlimited", lonely["cpu"]["limit_cores"] is None)

    logs = D.container_logs("shop_web_1", tail=100, docker_path=docker)
    check("logs parsed", len(logs) == 4)
    check("logs first message", logs[0]["message"] == "starting up")


def test_stacks_inspect_failure_falls_back(tmp_path=None):
    """If the batched inspect fails, /docker/stacks must still return — CPU
    limits just degrade to None (meters hatch), endpoint never breaks."""
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)
    os.environ["FAKE_DOCKER_INSPECT_FAIL"] = "1"
    try:
        stacks = D.stacks(docker_path=docker, timeout_seconds=8.0)
        check("stacks still returned on inspect fail", len(stacks) == 2)
        allc = [c for s in stacks for c in s["containers"]]
        check("all cpu limits None on inspect fail",
              all(c["cpu"]["limit_cores"] is None for c in allc))
        check("all cpu percent None on inspect fail",
              all(c["cpu"]["percent"] is None for c in allc))
        # used_cores is still computed from stats regardless.
        check("used_cores still present", any(c["cpu"]["used_cores"] > 0 for c in allc))
    finally:
        os.environ.pop("FAKE_DOCKER_INSPECT_FAIL", None)


def test_wrapper_daemon_unreachable(tmp_path=None):
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)
    os.environ["FAKE_DOCKER_FAIL"] = "1"
    try:
        raised = False
        try:
            D.overview(docker_path=docker, timeout_seconds=8.0)
        except D.DockerError as exc:
            raised = True
            check("error message surfaces daemon line", "daemon" in str(exc).lower())
        check("DockerError raised on rc!=0", raised)
    finally:
        os.environ.pop("FAKE_DOCKER_FAIL", None)


def test_wrapper_missing_binary():
    raised = False
    try:
        D.overview(docker_path="/nonexistent/docker-xyz", timeout_seconds=2.0)
    except D.DockerError as exc:
        raised = True
        check("missing binary message", "not found" in str(exc).lower())
    check("DockerError on missing binary", raised)


def test_logs_wrapper_stderr_is_content(tmp_path=None):
    """docker logs writes container stderr to our stderr — must be kept as log
    content, not treated as an error."""
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)
    os.environ["FAKE_DOCKER_LOGS_STDERR"] = "1"
    try:
        logs = D.container_logs("shop_web_1", tail=100, docker_path=docker)
        msgs = [l["message"] for l in logs]
        check("stderr line included as content", any("warn from stderr" in m for m in msgs))
    finally:
        os.environ.pop("FAKE_DOCKER_LOGS_STDERR", None)


def test_strip_docker_cli_noise():
    """docker's own CLI diagnostics on stderr (e.g. the root-owned config-file
    warning) must be dropped, while real log lines — even ones containing the
    word 'warning' — pass through untouched."""
    raw = (
        "WARNING: Error loading config file: open /home/marnarmon/.docker/config.json: permission denied\n"
        "2024-01-02T03:04:05Z app started\n"
        "2024-01-02T03:04:06Z warning: disk almost full\n"
    )
    out = D._strip_docker_cli_noise(raw)
    check("cli warning dropped", "Error loading config file" not in out)
    check("real log kept", "app started" in out)
    check("real 'warning' line kept", "disk almost full" in out)
    check("empty passthrough", D._strip_docker_cli_noise("") == "")


def test_logs_wrapper_hard_error(tmp_path=None):
    """rc!=0 AND no stdout (e.g. 'No such container') is a hard error."""
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)
    os.environ["FAKE_DOCKER_LOGS_RC"] = "1"
    try:
        raised = False
        try:
            D.container_logs("shop_web_1", tail=100, docker_path=docker)
        except D.DockerError:
            raised = True
        check("DockerError on no-such-container", raised)
    finally:
        os.environ.pop("FAKE_DOCKER_LOGS_RC", None)


# --------------------------------------------------------------------------- #
# API endpoint tests (FastAPI TestClient) — token gate + 503 gate
# --------------------------------------------------------------------------- #
def _api_client():
    """Import api against the example config and return (client, api, cfg).

    We mutate api.cfg per-test (the endpoints read cfg at call time), which is
    simpler than reloading the module and matches how cfg is a module global.
    """
    os.environ.setdefault(
        "MARNARMON_CONFIG",
        os.path.join(HERE, "..", "config", "config.example.yml"),
    )
    from fastapi.testclient import TestClient
    from marnarmon import api

    return TestClient(api.app, raise_server_exceptions=False), api


def test_api_docker_disabled_503():
    try:
        client, api = _api_client()
    except Exception as exc:  # httpx/TestClient unavailable
        check(f"SKIP api tests ({exc})", True)
        return
    api.cfg.docker_enabled = False
    api.cfg.api_token = ""
    for path in ("/docker/overview", "/docker/stacks", "/docker/logs?container=web"):
        r = client.get(path)
        check(f"{path} -> 503 when disabled", r.status_code == 503)
        check(f"{path} -> docker_disabled code", r.json().get("code") == "docker_disabled")


def test_api_docker_requires_token():
    try:
        client, api = _api_client()
    except Exception as exc:
        check(f"SKIP api tests ({exc})", True)
        return
    api.cfg.docker_enabled = True
    api.cfg.api_token = "s3cr3t-token"
    # Point the API at our fake docker so a *successful* auth path also works.
    import tempfile
    api.cfg.docker_path = _fake_docker_path(tempfile.mkdtemp())

    for path in ("/docker/overview", "/docker/stacks", "/docker/logs?container=shop_web_1"):
        r = client.get(path)
        check(f"{path} -> 401 without token", r.status_code == 401)
        r2 = client.get(path, headers={"Authorization": "Bearer wrong"})
        check(f"{path} -> 401 with wrong token", r2.status_code == 401)
        r3 = client.get(path, headers={"Authorization": "Bearer s3cr3t-token"})
        check(f"{path} -> 200 with token", r3.status_code == 200)
    # Restore so ordering between tests can't leak an enabled/token state.
    api.cfg.api_token = ""
    api.cfg.docker_enabled = False


def test_api_docker_overview_shape_with_token():
    try:
        client, api = _api_client()
    except Exception as exc:
        check(f"SKIP api tests ({exc})", True)
        return
    import tempfile
    api.cfg.docker_enabled = True
    api.cfg.api_token = ""
    api.cfg.docker_path = _fake_docker_path(tempfile.mkdtemp())

    r = client.get("/docker/overview")
    check("overview 200", r.status_code == 200)
    body = r.json()
    check("overview docker_ok true", body["docker_ok"] is True)
    check("overview has totals", body.get("totals") is not None)
    check("overview stats running=3", body["stats"]["running"] == 3)

    # Daemon-down path returns 200 with docker_ok=false (banner, not 5xx). Drop
    # the memoized snapshot first so this request actually shells out (the prior
    # healthy call populated the cache within its TTL).
    D.reset_cache()
    os.environ["FAKE_DOCKER_FAIL"] = "1"
    try:
        r2 = client.get("/docker/overview")
        check("daemon-down still 200", r2.status_code == 200)
        check("daemon-down docker_ok false", r2.json()["docker_ok"] is False)
    finally:
        os.environ.pop("FAKE_DOCKER_FAIL", None)
    api.cfg.docker_enabled = False


def test_api_docker_logs_bad_container_rejected():
    """An injection-shaped container ref must not reach argv — build_logs_args
    raises DockerError, surfaced as a 502 (same shape logs errors use)."""
    try:
        client, api = _api_client()
    except Exception as exc:
        check(f"SKIP api tests ({exc})", True)
        return
    import tempfile
    api.cfg.docker_enabled = True
    api.cfg.api_token = ""
    api.cfg.docker_path = _fake_docker_path(tempfile.mkdtemp())

    r = client.get("/docker/logs", params={"container": "web; rm -rf /"})
    check("injection container -> 502", r.status_code == 502)
    api.cfg.docker_enabled = False


# --------------------------------------------------------------------------- #
# Net rate, volume disk, restart count, caching (transparency upgrades)
# --------------------------------------------------------------------------- #
def test_compute_net_rates():
    """Aggregate net throughput is a bytes/sec delta between two stats snapshots;
    first sight and counter resets contribute 0, vanished containers drop out."""
    s1 = D.parse_stats(STATS)
    rx, tx, prev = D.compute_net_rates(s1, {}, now=100.0)
    check("first poll rx 0 (no prior sample)", rx == 0.0)
    check("first poll tx 0", tx == 0.0)
    check("prev captured for all present", set(prev.keys()) == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"})

    # Second poll 10s later: web rx grew 1.2kB -> 11.2kB (=10kB over 10s = 1000 B/s).
    s2 = D.parse_stats(
        '{"ID":"aaaaaaaaaaaa","Name":"shop_web_1","CPUPerc":"1%","MemUsage":"1MiB / 2MiB",'
        '"MemPerc":"1%","NetIO":"11.2kB / 3.4kB","BlockIO":"0B / 0B"}\n'
    )
    rx2, tx2, prev2 = D.compute_net_rates(s2, prev, now=110.0)
    check("rx rate = delta/dt", abs(rx2 - 1000.0) < 1e-6)
    check("tx unchanged -> 0 rate", tx2 == 0.0)
    check("prev pruned to present container only", set(prev2.keys()) == {"aaaaaaaaaaaa"})

    # Counter went backwards (container restarted) -> 0, never negative.
    s3 = D.parse_stats(
        '{"ID":"aaaaaaaaaaaa","Name":"shop_web_1","CPUPerc":"1%","MemUsage":"1MiB / 2MiB",'
        '"MemPerc":"1%","NetIO":"200B / 3.4kB","BlockIO":"0B / 0B"}\n'
    )
    rx3, _, _ = D.compute_net_rates(s3, prev2, now=120.0)
    check("counter reset clamps to 0", rx3 == 0.0)


LONGID = "b" * 64
INSPECT_MOUNTS = (
    '[{"Id":"%s","Mounts":[{"Type":"bind","Source":"/x","Destination":"/x"},'
    '{"Type":"volume","Name":"dbdata","Destination":"/d"},'
    '{"Type":"volume","Name":"logs","Destination":"/l"}]},'
    '{"Id":"cccccccccccc"}]' % LONGID
)


def test_parse_inspect_mounts():
    m = D.parse_inspect_mounts(INSPECT_MOUNTS)
    check("bind mounts ignored, named volumes kept", m[LONGID] == ["dbdata", "logs"])
    check("keyed by short id too", m[LONGID[:12]] == ["dbdata", "logs"])
    check("container with no Mounts -> []", m["cccccccccccc"] == [])
    check("bad input -> {}", D.parse_inspect_mounts("x") == {})
    check("non-array -> {}", D.parse_inspect_mounts('{"Id":"z"}') == {})


def test_parse_df_verbose_volumes():
    raw = '{"Volumes":[{"Name":"shop_dbdata","Size":"512MB"},{"Name":"cache","Size":"7MiB"}]}'
    vols = D.parse_df_verbose_volumes(raw)
    check("volume size parsed (SI)", vols["shop_dbdata"] == 512 * 1000 ** 2)
    check("second volume (binary)", abs(vols["cache"] - 7 * 1024 ** 2) < 1)
    check("bad input -> {}", D.parse_df_verbose_volumes("nonsense") == {})
    check("empty -> {}", D.parse_df_verbose_volumes("") == {})


def test_count_restart_events():
    raw = (
        '{"Type":"container","Action":"restart"}\n\n'
        '{"Type":"container","Action":"restart"}\n'
        '{"Type":"container","Action":"die"}\n'
    )
    check("counts only restart actions", D.count_restart_events(raw) == 2)
    check("empty -> 0", D.count_restart_events("") == 0)
    # Filter is applied in the argv; a line with no Action is still a restart.
    check("no-action line counted", D.count_restart_events('{"Type":"container"}\n') == 1)


def test_build_events_args():
    a = D.build_events_args(1000, 2000, "docker")
    check("events subcommand", a[:2] == ["docker", "events"])
    check("since/until epochs as ints", "--since" in a and "1000" in a and "2000" in a)
    check("filtered to container restart", "type=container" in a and "event=restart" in a)


def test_build_overview_net_and_restarts():
    ov = D.build_overview(
        [], {}, {}, host_mem_total=HOST_MEM, host_cores=4, host_disk_total=100 * 1000 ** 3,
        net_rx_rate=1500.0, net_tx_rate=250.0, restarts_24h=7,
    )
    check("net rx rate passthrough", ov["stats"]["net_rx_rate"] == 1500.0)
    check("net tx rate passthrough", ov["stats"]["net_tx_rate"] == 250.0)
    check("restarts passthrough", ov["stats"]["restarts_24h"] == 7)
    dflt = D.build_overview([], {}, {}, host_mem_total=HOST_MEM, host_cores=4, host_disk_total=1)
    check("defaults to 0 restarts", dflt["stats"]["restarts_24h"] == 0)
    check("defaults to 0 rate", dflt["stats"]["net_rx_rate"] == 0.0)


def test_container_volume_disk():
    """Named-volume bytes join into each container's disk + the stack rollup."""
    containers = D.parse_ps(PS)
    stats = D.parse_stats(STATS)
    vols = {"bbbbbbbbbbbb": 512 * 1000 ** 2}  # db's volume total
    stacks = D.group_stacks(containers, stats, HOST_MEM, None, vols)
    shop = next(s for s in stacks if s["name"] == "shop")
    db = next(c for c in shop["containers"] if c["name"] == "shop_db_1")
    check("db volume bytes attributed", db["disk"]["volumes_bytes"] == 512 * 1000 ** 2)
    check("db disk = rw layer + volumes",
          abs(db["disk"]["bytes"] - (40 * 1000 ** 2 + 512 * 1000 ** 2)) < 1)
    web = next(c for c in shop["containers"] if c["name"] == "shop_web_1")
    check("web has no volume -> 0", web["disk"]["volumes_bytes"] == 0.0)
    check("stack disk rollup includes the volume", shop["disk_bytes"] >= 512 * 1000 ** 2)


def test_cache_layer():
    """_cached: TTL 0 always produces (nothing stored); TTL>0 memoizes."""
    slot = {"data": None, "at": 0.0}
    calls = {"n": 0}

    def produce():
        calls["n"] += 1
        return calls["n"]

    check("ttl0 produces", D._cached(slot, 0, produce) == 1)
    check("ttl0 produces again", D._cached(slot, 0, produce) == 2)
    check("ttl0 stores nothing", slot["data"] is None)
    check("ttl produce first", D._cached(slot, 100, produce) == 3)
    check("ttl reuses cached", D._cached(slot, 100, produce) == 3)
    check("ttl stored the value", slot["data"] == 3)


def test_overview_and_stacks_caching_end_to_end(tmp_path=None):
    """With caching active: /overview counts real restarts, first-poll net rate is
    0, and /stacks reports real per-container volume disk from `df -v`."""
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)
    D.reset_cache()
    try:
        ov = D.overview(docker_path=docker, timeout_seconds=8.0,
                        stats_cache_seconds=30.0, events_cache_seconds=30.0)
        check("restarts_24h from docker events", ov["stats"]["restarts_24h"] == 3)
        check("first-poll net rx rate 0", ov["stats"]["net_rx_rate"] == 0.0)

        st = D.stacks(docker_path=docker, timeout_seconds=8.0,
                      stats_cache_seconds=30.0, df_cache_seconds=60.0)
        shop = next(s for s in st if s["name"] == "shop")
        db = next(c for c in shop["containers"] if c["name"] == "shop_db_1")
        check("db real volume disk via df -v", db["disk"]["volumes_bytes"] == 512 * 1000 ** 2)
        web = next(c for c in shop["containers"] if c["name"] == "shop_web_1")
        check("web (bind mount only) volume disk 0", web["disk"]["volumes_bytes"] == 0.0)
    finally:
        D.reset_cache()


def test_overview_events_failure_degrades(tmp_path=None):
    """A failing `docker events` degrades restarts_24h to 0 — overview still 200s."""
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)
    D.reset_cache()
    os.environ["FAKE_DOCKER_EVENTS_FAIL"] = "1"
    try:
        ov = D.overview(docker_path=docker, timeout_seconds=8.0)
        check("events fail -> restarts 0", ov["stats"]["restarts_24h"] == 0)
        check("overview still returns totals", "totals" in ov and "stats" in ov)
    finally:
        os.environ.pop("FAKE_DOCKER_EVENTS_FAIL", None)
        D.reset_cache()


def test_overview_caches_summary_df(tmp_path=None):
    """The summary `docker system df` is cached: a second overview() within the
    TTL does NOT re-run it (the cache slot's timestamp is unchanged), and the
    disk totals are served identically from cache."""
    import tempfile
    tmp = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    docker = _fake_docker_path(tmp)
    D.reset_cache()
    try:
        ov1 = D.overview(docker_path=docker, timeout_seconds=8.0,
                         stats_cache_seconds=30.0, df_cache_seconds=60.0)
        at1 = D._df_summary_cache["at"]
        check("summary df cached (slot populated)", D._df_summary_cache["data"] is not None)
        check("disk used from df", ov1["totals"]["disk"]["used_bytes"] > 0)

        ov2 = D.overview(docker_path=docker, timeout_seconds=8.0,
                         stats_cache_seconds=30.0, df_cache_seconds=60.0)
        check("summary df NOT re-fetched within TTL", D._df_summary_cache["at"] == at1)
        check("disk totals identical from cache",
              ov1["totals"]["disk"]["used_bytes"] == ov2["totals"]["disk"]["used_bytes"])
    finally:
        D.reset_cache()


def test_mem_available_flag():
    """totals.mem.available is False only when there ARE running containers but
    the summed memory is 0 (the host memory cgroup is disabled — the Pi default);
    True when memory is reported, and True when there are no running containers."""
    running_container = [c for c in D.parse_ps(PS) if c["state_raw"].lower() == "running"][:1]

    # cgroup off: running containers, zero mem reported by docker stats.
    off = D.build_overview(running_container, {}, {}, host_mem_total=HOST_MEM,
                           host_cores=4, host_disk_total=1)
    check("mem unavailable when running + zero mem", off["totals"]["mem"]["available"] is False)

    # real memory reported -> available.
    on = D.build_overview(D.parse_ps(PS), D.parse_stats(STATS), {},
                          host_mem_total=HOST_MEM, host_cores=4, host_disk_total=1)
    check("mem available when memory reported", on["totals"]["mem"]["available"] is True)

    # nothing running -> not flagged as unavailable.
    empty = D.build_overview([], {}, {}, host_mem_total=HOST_MEM, host_cores=4,
                             host_disk_total=1)
    check("mem available when nothing running", empty["totals"]["mem"]["available"] is True)


def test_container_host_percent():
    """Per-container mem/cpu carry host_percent (share of whole host) — the UI's
    fallback meter fill when the container sets no explicit limit."""
    web = next(c for c in D.parse_ps(PS) if c["name"] == "shop_web_1")
    vm = D._container_vm(web, D.parse_stats(STATS), HOST_MEM, host_cores=4)
    # web: 64MiB used of an 8GiB host.
    check("mem host_percent = used/host",
          abs(vm["mem"]["host_percent"] - (64 * 1024 ** 2 / HOST_MEM * 100)) < 1e-6)
    # web: 12.5% CPU == 0.125 cores of 4 host cores.
    check("cpu host_percent = cores/host_cores",
          abs(vm["cpu"]["host_percent"] - (0.125 / 4 * 100)) < 1e-6)
    # No host_cores available -> host_percent None (no divide-by-zero).
    vm0 = D._container_vm(web, D.parse_stats(STATS), 0, host_cores=0)
    check("cpu host_percent None without host_cores", vm0["cpu"]["host_percent"] is None)
    check("mem host_percent None without host_mem", vm0["mem"]["host_percent"] is None)


# --------------------------------------------------------------------------- #
# Bare runner (no pytest) — mirrors test_logs.py main().
# --------------------------------------------------------------------------- #
def main():
    tests = [
        test_parse_size,
        test_parse_size_pair,
        test_parse_percent,
        test_health_label,
        test_classify_state,
        test_build_simple_args,
        test_build_logs_args_ok,
        test_since_whitelist,
        test_container_whitelist_rejects_injection,
        test_build_inspect_args,
        test_parse_stats,
        test_parse_ps,
        test_parse_system_df,
        test_parse_inspect_cpu,
        test_parse_inspect_cpu_tolerant,
        test_container_cpu_limit_from_inspect,
        test_parse_ps_empty_and_malformed,
        test_group_stacks,
        test_mem_limit_semantics,
        test_group_stacks_empty,
        test_build_overview,
        test_build_overview_empty,
        test_parse_logs,
        test_wrappers_end_to_end,
        test_stacks_inspect_failure_falls_back,
        test_wrapper_daemon_unreachable,
        test_wrapper_missing_binary,
        test_logs_wrapper_stderr_is_content,
        test_logs_wrapper_hard_error,
        test_api_docker_disabled_503,
        test_api_docker_requires_token,
        test_api_docker_overview_shape_with_token,
        test_api_docker_logs_bad_container_rejected,
        test_compute_net_rates,
        test_parse_inspect_mounts,
        test_parse_df_verbose_volumes,
        test_count_restart_events,
        test_build_events_args,
        test_build_overview_net_and_restarts,
        test_container_volume_disk,
        test_cache_layer,
        test_overview_and_stacks_caching_end_to_end,
        test_overview_events_failure_degrades,
        test_overview_caches_summary_df,
        test_mem_available_flag,
        test_container_host_percent,
    ]
    print("Running MarNarMon docker tests...")
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
