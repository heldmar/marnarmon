"""Unit tests for the journald log reader (logs.py).

Fixture-based: no live journal required, so these run anywhere. The subprocess
wrappers (_run/query/list_sources) do the only real I/O and are exercised
manually on a host; everything tricky (arg-building, JSON-lines parsing,
priority mapping, source denoising) is a pure function tested here. Run:

    cd host && python -m pytest ../tests -q
    # or, without pytest:
    python ../tests/test_logs.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host"))

from marnarmon import logs as L  # noqa: E402

# One JSON object per line, exactly like `journalctl --output=json` emits.
# Includes: a normal service line, a kernel line (no _SYSTEMD_UNIT), a line
# whose MESSAGE is a byte array (non-UTF8 payload), a blank line and a
# malformed line — the parser must survive all of them.
JOURNAL_JSON = """{"__REALTIME_TIMESTAMP":"1700000000000000","__CURSOR":"c1","PRIORITY":"3","MESSAGE":"connection refused","_SYSTEMD_UNIT":"nginx.service","_HOSTNAME":"pi","_PID":"123"}
{"__REALTIME_TIMESTAMP":"1700000001500000","__CURSOR":"c2","PRIORITY":"4","MESSAGE":"Out of memory: killed process","_TRANSPORT":"kernel","_HOSTNAME":"pi"}

{"__REALTIME_TIMESTAMP":"1700000002000000","__CURSOR":"c3","PRIORITY":"6","MESSAGE":[72,105,255,33],"_SYSTEMD_UNIT":"app.service"}
{ this is not valid json
{"__REALTIME_TIMESTAMP":"1700000003000000","__CURSOR":"c4","PRIORITY":"6","MESSAGE":"sshd accepted login","SYSLOG_IDENTIFIER":"sshd","_TRANSPORT":"syslog"}
"""

SOURCES_F = """-
nginx.service
ssh.service
session-42.scope
run-abc.scope
dev-sda1.mount
system.slice
docker.service
"""


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        raise AssertionError(name)


def test_priority_mapping():
    check("label 0 Emergency", L.priority_label(0) == "Emergency")
    check("label 3 Error", L.priority_label(3) == "Error")
    check("label 4 Warning", L.priority_label(4) == "Warning")
    check("label 6 Info", L.priority_label(6) == "Info")
    check("label 7 Debug", L.priority_label(7) == "Debug")
    check("bucket 0 error", L.priority_bucket(0) == "error")
    check("bucket 3 error", L.priority_bucket(3) == "error")
    check("bucket 4 warning", L.priority_bucket(4) == "warning")
    check("bucket 6 info", L.priority_bucket(6) == "info")
    check("bucket 7 debug", L.priority_bucket(7) == "debug")


def test_parse_json_lines():
    lines = L.parse_json_lines(JOURNAL_JSON)
    # 4 valid records; blank line and malformed line skipped.
    check("parsed 4 records (blank+bad skipped)", len(lines) == 4)

    nginx = lines[0]
    check("nginx ts seconds", nginx["ts"] == 1700000000)
    check("nginx unit", nginx["unit"] == "nginx.service")
    check("nginx source == unit", nginx["source"] == "nginx.service")
    check("nginx severity error", nginx["severity"] == "error")
    check("nginx severity label", nginx["severity_label"] == "Error")
    check("nginx cursor", nginx["cursor"] == "c1")

    kernel = lines[1]
    check("kernel source synthesized", kernel["source"] == L.KERNEL_SOURCE)
    check("kernel unit is None", kernel["unit"] is None)
    check("kernel label friendly", kernel["source_label"] == "Kernel")

    app = lines[2]
    # bytes [72,105,255,33] = 'H','i',<invalid>,'!'  -> "Hi�!"
    check("byte-array message decoded", app["message"].startswith("Hi"))
    check("byte-array message end", app["message"].endswith("!"))
    check("byte-array replacement char", "�" in app["message"])

    sshd = lines[3]
    # No unit, syslog transport -> fall back to SYSLOG_IDENTIFIER for source.
    check("syslog identifier source", sshd["source"] == "sshd")


def test_build_args():
    a = L.build_args(
        since_ts=1700000000,
        until_ts=1700003600,
        units=["nginx.service", "kernel"],
        severity="errors",
        keyword="disk full",
        limit=50,
    )
    check("base output json", "--output=json" in a and "--no-pager" in a)
    check("reverse newest-first", "--reverse" in a)
    check("since epoch @", "--since=@1700000000" in a)
    check("until epoch @", "--until=@1700003600" in a)
    check("severity errors -> priority 3", "--priority=3" in a)
    check("keyword grep escaped literal", "--grep=disk\\ full" in a)
    check("keyword case-insensitive", "--case-sensitive=false" in a)
    check("limit lines", "--lines=50" in a)
    # OR of a real unit and the kernel transport, joined by journalctl '+'.
    check("unit match present", "_SYSTEMD_UNIT=nginx.service" in a)
    check("kernel transport match", "_TRANSPORT=kernel" in a)
    check("or-join token", "+" in a)

    # severity 'all' emits no --priority (shows everything incl. debug).
    b = L.build_args(severity="all")
    check("severity all -> no priority flag", not any(x.startswith("--priority") for x in b))

    # warnings threshold is cumulative (0..4), so errors remain visible.
    c = L.build_args(severity="warnings")
    check("severity warnings -> priority 4", "--priority=4" in c)

    # only kernel selected -> no stray '+' separator.
    d = L.build_args(units=["kernel"])
    check("kernel-only no plus", "+" not in d and "_TRANSPORT=kernel" in d)


def test_parse_sources():
    units = L.parse_sources(SOURCES_F)
    check("real units kept", "nginx.service" in units and "ssh.service" in units)
    check("docker kept", "docker.service" in units)
    check("scope denied", not any(u.endswith(".scope") for u in units))
    check("mount denied", not any(u.endswith(".mount") for u in units))
    check("slice denied", not any(u.endswith(".slice") for u in units))
    check("placeholder dash dropped", "-" not in units)
    check("sorted", units == sorted(units))


def test_friendly_labels():
    check("strip .service + titlecase", L.friendly_source_label("nginx.service") == "Nginx")
    check("kernel label", L.friendly_source_label("kernel") == "Kernel")
    check("separators to spaces", L.friendly_source_label("systemd-journald.service") == "Systemd journald")


def main():
    tests = [
        test_priority_mapping,
        test_parse_json_lines,
        test_build_args,
        test_parse_sources,
        test_friendly_labels,
    ]
    print("Running MarNarMon logs tests...")
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
