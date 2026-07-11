#!/usr/bin/env bash
#
# update-dashboard.sh — redeploy the CFNS MarNarMon dashboard from GitHub.
# Clones the repo fresh into a temp dir each run (nothing persists in $HOME),
# builds, and cleans up. Place at /home/ubuntu/update-dashboard.sh. Run: ./update-dashboard.sh
#
set -euo pipefail

# ---- Config -----------------------------------------------------------------
REPO_URL="https://github.com/heldmar/marnarmon.git"
STACK_DIR="/home/ubuntu/containers/marnarmon-dashboard"
NPM_NETWORK="npm-proxy_npm-network"                  # NPM's docker network
# -----------------------------------------------------------------------------

# Use sudo for docker only if the current user can't reach the daemon directly.
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; fi

# Fresh temp checkout, always cleaned up (even on error).
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT

echo "==> Cloning ${REPO_URL} (shallow)"
git clone --depth 1 "${REPO_URL}" "${TMP_DIR}/repo"

echo "==> Syncing dashboard source into ${STACK_DIR}"
mkdir -p "${STACK_DIR}"
cp -r "${TMP_DIR}"/repo/dashboard/. "${STACK_DIR}"/

echo "==> Writing CFNS docker-compose.yml (overwrites the repo's Pi version)"
cat > "${STACK_DIR}/docker-compose.yml" <<EOF
services:
  dashboard:
    build: .
    image: marnarmon-dashboard:latest
    pull_policy: build
    container_name: marnarmon-dashboard
    ports:
      - "8080:80"
    environment:
      API_BASE_URL: "/api"
      API_UPSTREAM: "http://host.docker.internal:8787"
      REFRESH_SECONDS: "300"
      LOGS_REFRESH_SECONDS: "10"
      API_TOKEN: "\${API_TOKEN:-}"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
    networks:
      - default
      - npm-network

networks:
  npm-network:
    external: true
    name: ${NPM_NETWORK}
EOF

# The API token lives in .env (not in git). Warn if it went missing.
if [ ! -f "${STACK_DIR}/.env" ]; then
  echo "  !! ${STACK_DIR}/.env is missing — the dashboard will 401 against the agent."
  echo "     Recreate it with:  echo 'API_TOKEN=<your-token>' > ${STACK_DIR}/.env"
fi

echo "==> Rebuilding and restarting the stack"
cd "${STACK_DIR}"
${DOCKER} compose up -d --build

echo "==> Health check"
sleep 3
if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
  echo "  OK — dashboard is up and proxying to the agent."
else
  echo "  !! /api/health not responding yet. Check: ${DOCKER} compose logs --tail 30"
fi

echo "==> Done.  https://dashboard.cfns.us"
