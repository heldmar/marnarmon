# Docker Monitor — enable & operate

How to enable (and roll back) the **Docker Monitor** feature on an
**already-running** MarNarMon install, on **any systemd Linux host** (cloud VM,
bare metal, Raspberry Pi, …).

The host agent runs under **systemd** (it is *not* itself containerized): code
lives at `/opt/marnarmon/marnarmon`, config at `/etc/marnarmon/config.yml`, the
API unit at `/etc/systemd/system/marnarmon-api.service`, and it runs as the
unprivileged `marnarmon` user.

> **Already installed and just want the latest code?** Use the updater instead
> of the manual steps here: from a checkout of this repo,
> `sudo ./update.sh --engine` pulls the latest release and restarts the service
> (it never rewrites your config or token). This runbook is for the one-time
> **enable/disable** of Docker Monitor. See [`../update.sh --help`](../update.sh).

> **Running privileged steps.** Each privileged block below is delivered as a
> small script you **write to a file first, then run with `sudo bash <file>`**.
> If your host uses **password** sudo (not passwordless), do *not* pipe the
> script into `sudo` via a heredoc (`sudo bash <<'EOF' … EOF`): that feeds the
> script to `sudo` on **stdin**, the same channel `sudo` needs for the password
> prompt, so it hangs. Writing the file first keeps stdin free for the password.
> On a passwordless-sudo host either form works. Each block self-cleans its temp
> file; nothing is left behind.

---

## READ THIS FIRST — the security trade-off

Enabling Docker Monitor adds the `marnarmon` service user to the **`docker`
group**. Docker-group membership is **effectively ROOT-EQUIVALENT**: anyone who
can reach the API can drive the Docker daemon and therefore take over the host.

The `/docker/*` endpoints are protected only by the **API bearer token** (and
restricted CORS) from the Server Logs phase. So before enabling, confirm:

- `api.token` in `/etc/marnarmon/config.yml` is **set** (non-empty).
- The API is bound to `127.0.0.1`, **or** it is only reachable behind the
  authenticated reverse proxy — not naked on the LAN.
- `api.allowed_origins` is restricted to your dashboard origin(s), not `["*"]`,
  if the API is reachable from untrusted networks.

If the token is empty, **do not enable this** until you have set one (set
`api.token` in the config and restart the API).

Check the current token/bind before you start:

```bash
sudo grep -E '^\s*(host|port|token|allowed_origins):' /etc/marnarmon/config.yml
```

---

## Recommended — update the host code + enable, from a fresh clone (single command)

This is the clean, git-native path for an **already-configured** install: it
pulls the current `main` into a throwaway temp dir, syncs just the host-agent
Python files into `/opt/marnarmon/marnarmon` (no new deps — the venv is
untouched), enables Docker Monitor, restarts, and deletes the clone. It
**preserves your existing config** (token, disks, Server Logs) — it never
rewrites `config.yml` wholesale. Idempotent and self-cleaning; nothing is left
behind on the server.

First write the script to a file (runs as your normal user — no sudo yet):

```bash
cat > /tmp/marnar-enable.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
REPO=https://github.com/heldmar/marnarmon.git
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 "$REPO" "$TMP/repo"

# 0. Sync the host-agent code. No new dependencies, so the venv stays as-is.
#    Preserve the existing package files' owner/mode.
DST=/opt/marnarmon/marnarmon
OWNER=$(stat -c '%U' "$DST/api.py"); GROUP=$(stat -c '%G' "$DST/api.py"); MODE=$(stat -c '%a' "$DST/api.py")
for f in docker.py api.py config.py; do
  install -o "$OWNER" -g "$GROUP" -m "$MODE" "$TMP/repo/host/marnarmon/$f" "$DST/$f"
done

# 1. Grant the service user docker-group access (ROOT-EQUIVALENT — see above).
usermod -aG docker marnarmon

# 2. Add SupplementaryGroups=docker via a drop-in (additive; merges with any
#    existing SupplementaryGroups= such as systemd-journal). Reversible: the
#    rollback simply deletes this file.
install -d /etc/systemd/system/marnarmon-api.service.d
cat > /etc/systemd/system/marnarmon-api.service.d/docker.conf <<'CONF'
[Service]
SupplementaryGroups=docker
CONF

# 3. Enable Docker Monitor in the config (append the block if absent, else flip
#    enabled: true inside the existing docker: block). Existing keys are kept.
CFG=/etc/marnarmon/config.yml
if ! grep -qE '^docker:' "$CFG"; then
  cat >> "$CFG" <<'YML'
docker:
  # SECURITY: docker access is root-equivalent. Keep api.token set and the API
  # bound to localhost / behind an authenticated reverse proxy.
  enabled: true
  path: "docker"
  timeout_seconds: 8.0
  logs_default_tail: 200
  logs_max_tail: 1000
  stats_cache_seconds: 3.0
  df_cache_seconds: 60.0
  events_cache_seconds: 30.0
YML
else
  sed -i '/^docker:/,/^[^[:space:]#]/ s/^\(\s*enabled:\).*/\1 true/' "$CFG"
fi
chown root:marnarmon "$CFG"; chmod 640 "$CFG"

# 4. Apply. daemon-reload picks up the drop-in; restart (not just reload) is
#    required so the process re-reads config AND picks up the new group.
systemctl daemon-reload
systemctl restart marnarmon-api.service
echo "Host agent updated + Docker Monitor enabled."
EOF
```

Then run it with sudo (you'll be prompted for your password), and clean up:

```bash
sudo bash /tmp/marnar-enable.sh
rm -f /tmp/marnar-enable.sh
```

> Re-running this is safe and idempotent (the `usermod`/drop-in/config steps
> no-op if already applied). But once Docker Monitor is enabled, the simpler way
> to **pick up new releases** is `sudo ./update.sh --engine` — it pulls the
> latest tag, re-syncs the code, updates venv deps if they changed, and restarts.

> **Do not use `sudo ./install.sh` to update a live install.** That installer is
> a first-time provisioner — it rewrites `config.yml` from your prompt answers
> and **regenerates the API token**, which would break the dashboard's auth. Use
> it only for a fresh host (or if you deliberately re-enter every existing
> answer). The command above is the safe way to update an existing, configured
> server.

---

## Verify

Set your token first (copy it from the config), then run the checks. Use
`127.0.0.1` — do the checks locally on the Pi.

```bash
TOKEN="$(sudo sed -n 's/^\s*token:\s*"\(.*\)"/\1/p' /etc/marnarmon/config.yml)"
BASE="http://127.0.0.1:8787"

# 1. Feature flag is on:
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/health" | grep -o '"docker":[a-z]*'
#   expect: "docker":true

# 2. Authenticated /docker/overview returns 200:
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" "$BASE/docker/overview"
#   expect: 200   (a 200 with docker_ok:false just means the daemon was
#                  unreachable — auth/enablement are still correct)

# 3. Unauthenticated request is rejected:
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/docker/overview"
#   expect: 401   (if this is NOT 401, api.token is empty — STOP and set a
#                  token before leaving Docker Monitor enabled)
```

If the API doesn't come back, check: `journalctl -u marnarmon-api.service -n 50`.
A permission error on the docker socket usually means the group membership
hasn't taken effect — a `systemctl restart marnarmon-api.service` (not reload)
is required after the group change.

---

## Enable accurate memory stats (Raspberry Pi memory cgroup)

**Symptom:** the dashboard shows RAM as **"n/a"** / hatched and containers report
**0 B** of memory, while CPU and disk are correct.

**Cause:** Raspberry Pi OS ships with the kernel **memory cgroup controller
disabled** to save a little RAM. Without it, `docker stats` reports `MEM 0B / 0B`
for every container, so there is nothing for the agent to read. Confirm with:

```bash
cat /sys/fs/cgroup/cgroup.controllers
#   if the list has no "memory", the controller is off (CPU still works)
```

**Fix:** add two flags to the kernel command line and reboot. `cmdline.txt` **must
stay a single line** — the script below appends to the first line and backs the
file up first.

```bash
cat > /tmp/marnar-cgroup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
F=/boot/firmware/cmdline.txt
[ -f "$F" ] || F=/boot/cmdline.txt          # older Raspberry Pi OS layout
cp -a "$F" "$F.bak.$(date +%s)"             # timestamped backup
if grep -q 'cgroup_enable=memory' "$F"; then
  echo "Already enabled — no change:"
else
  sed -i '1 s/$/ cgroup_enable=memory cgroup_memory=1/' "$F"  # append, keep 1 line
  echo "Appended cgroup flags. New cmdline:"
fi
cat "$F"
EOF
sudo bash /tmp/marnar-cgroup.sh
rm -f /tmp/marnar-cgroup.sh
```

Review the printed line (it must be **one** line), then reboot to apply:

```bash
sudo reboot
```

> ⚠️ **This reboots the Pi** — every service on it (Portainer, its stacks, the
> dashboard, anything else) goes down for the duration of the reboot. Do it at an
> approved, low-traffic time. Enabling the memory controller also costs a small,
> fixed amount of kernel RAM (accounting overhead) — negligible on a 4 GB Pi.

After it comes back, verify the controller is present and stats are real:

```bash
cat /sys/fs/cgroup/cgroup.controllers          # now includes "memory"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'   # non-zero MEM
```

The dashboard's Memory gauge and per-container RAM meters populate on the next
poll; the "memory cgroup disabled" banner disappears on its own.

> **Note (CPU):** `--no-stream` is fine for the MEM spot-check above, but it
> reports `0.00%` CPU for every container (a single sample has no interval to
> diff). To eyeball real CPU manually, stream instead and read the second frame:
> `docker stats --format '{{.Name}} {{.CPUPerc}}'` (Ctrl-C after it refreshes).
> The engine does this internally as of v1.0.4, so the dashboard shows real CPU.

---

## Roll back (disable Docker Monitor)

Single command; reverses all of Option B. Idempotent.

```bash
cat > /tmp/marnar-disable.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
# 1. Flip the config off.
CFG=/etc/marnarmon/config.yml
sed -i '/^docker:/,/^[^[:space:]#]/ s/^\(\s*enabled:\).*/\1 false/' "$CFG"

# 2. Remove the systemd drop-in that granted the docker group.
rm -f /etc/systemd/system/marnarmon-api.service.d/docker.conf
rmdir --ignore-fail-on-non-empty /etc/systemd/system/marnarmon-api.service.d 2>/dev/null || true

# 3. Remove the service user from the docker group (revokes root-equivalent access).
gpasswd -d marnarmon docker || true

# 4. Apply.
systemctl daemon-reload
systemctl restart marnarmon-api.service
echo "Docker Monitor disabled and docker-group access revoked."
EOF
sudo bash /tmp/marnar-disable.sh
rm -f /tmp/marnar-disable.sh
```

Confirm rollback: `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/health`
should now show `"docker":false`, and `/docker/overview` returns `503`
(`docker_disabled`).

> Note: the disable command above matches the recommended enable path (which
> uses a systemd **drop-in**). If Docker Monitor was instead enabled by a
> from-scratch `install.sh` run, the `SupplementaryGroups=docker` line is in the
> main unit file (`/etc/systemd/system/marnarmon-api.service`) and step 2's `rm`
> is a no-op — remove that line by hand. Steps 1, 3 and 4 above still apply. The
> updated `docker.py`/`api.py` can stay in place; with `enabled: false` the
> `/docker/*` endpoints simply return `503`.
