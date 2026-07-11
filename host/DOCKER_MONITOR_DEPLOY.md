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

If the token is empty, **do not enable this** until you have set one (re-run
`install.sh` and opt into token auth, or edit the config and restart).

Check the current token/bind before you start:

```bash
sudo grep -E '^\s*(host|port|token|allowed_origins):' /etc/marnarmon/config.yml
```

---

## Option A (recommended) — re-run the installer

The installer is idempotent, detects Docker, and does everything below for you
(group, systemd line, config flip, restart). From the repo checkout on the Pi:

```bash
sudo ./install.sh
```

Answer **Yes** at the "Enable Docker Monitor?" prompt (it only appears when a
reachable Docker daemon is detected). Keep your existing answers for everything
else. Then jump to **Verify**.

---

## Option B — manual enable on a live install (single command)

Use this when you can't re-run the interactive installer. It (1) adds the
service user to `docker`, (2) adds `SupplementaryGroups=docker` via a systemd
**drop-in** (additive and trivially reversible — it composes with the existing
`systemd-journal` group if Server Logs is on), (3) enables `docker` in the
config, and (4) reloads + restarts the API. It is idempotent.

```bash
sudo bash -euo pipefail <<'EOF'
# 1. Grant the service user docker-group access (ROOT-EQUIVALENT — see runbook).
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
#    enabled: true inside the existing docker: block).
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
YML
else
  sed -i '/^docker:/,/^[^[:space:]#]/ s/^\(\s*enabled:\).*/\1 true/' "$CFG"
fi
chown root:marnarmon "$CFG"; chmod 640 "$CFG"

# 4. Apply. daemon-reload picks up the drop-in; restart (not just reload) is
#    required so the process re-reads config AND picks up the new group.
systemctl daemon-reload
systemctl restart marnarmon-api.service
echo "Docker Monitor enabled."
EOF
```

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

> Note: if you originally enabled via **Option A** (installer) rather than the
> drop-in, the `SupplementaryGroups=docker` line is in the main unit file
> (`/etc/systemd/system/marnarmon-api.service`). Step 2's `rm` is then a no-op;
> re-run `sudo ./install.sh` and answer **No** to fully re-render the unit, or
> remove that line by hand. Steps 1, 3 and 4 above still apply.
