# Docker Monitor — Pi deployment runbook

How to enable (and roll back) the **Docker Monitor** feature on an
**already-running** MarNarMon install on the Raspberry Pi.

The host agent runs under **systemd** (it is *not* itself containerized): code
lives at `/opt/marnarmon/marnarmon`, config at `/etc/marnarmon/config.yml`, the
API unit at `/etc/systemd/system/marnarmon-api.service`, and it runs as the
unprivileged `marnarmon` user.

> **Constraint:** on the Pi, `helder` has **no passwordless sudo**. Every
> privileged step below is delivered as a **single copy-pasteable `sudo`
> command** you run once and type your password for. Nothing here assumes
> passwordless escalation.

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

```bash
sudo bash -euo pipefail <<'EOF'
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

## Roll back (disable Docker Monitor)

Single command; reverses all of Option B. Idempotent.

```bash
sudo bash -euo pipefail <<'EOF'
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
