#!/bin/sh
# Regenerate the runtime config from environment variables on container start.
# Lets a single built image target any host without rebuilding.
set -e

CONFIG_PATH="/usr/share/nginx/html/config.js"
API_PROXY_PATH="/etc/nginx/marnarmon-api-proxy.conf"

# Browser-facing API base. Default "/api" = same-origin reverse proxy (below),
# which is what you want when the dashboard is served over public HTTPS. Set it
# to a full URL instead (e.g. http://192.168.4.200:8787) for direct LAN access.
API_BASE_URL="${API_BASE_URL:-/api}"

# Where nginx forwards /api/ — the host agent as reached FROM THE CONTAINER
# (LAN IP/host, reachable on the Docker network). Only used in same-origin mode.
API_UPSTREAM="${API_UPSTREAM:-http://localhost:8787}"
API_UPSTREAM="${API_UPSTREAM%/}"

cat > "$CONFIG_PATH" <<EOF
window.__MARNARMON_CONFIG__ = {
  API_BASE_URL: "${API_BASE_URL}",
  REFRESH_SECONDS: ${REFRESH_SECONDS:-300},
  LOGS_REFRESH_SECONDS: ${LOGS_REFRESH_SECONDS:-10},
  API_TOKEN: "${API_TOKEN:-}"
};
EOF

# Same-origin reverse proxy: /api/metrics/current -> $API_UPSTREAM/metrics/current.
# The trailing slash on proxy_pass strips the /api prefix. nginx includes this
# file from inside the server block (see nginx.conf). If the dashboard talks to
# the API directly (API_BASE_URL is a full URL), this block is simply unused.
cat > "$API_PROXY_PATH" <<EOF
location /api/ {
    proxy_pass ${API_UPSTREAM}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
EOF

echo "marnarmon-dashboard: wrote $CONFIG_PATH (API_BASE_URL=${API_BASE_URL})"
echo "marnarmon-dashboard: wrote $API_PROXY_PATH (/api/ -> ${API_UPSTREAM})"
