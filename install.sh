#!/usr/bin/env bash
#
# MarNarMon host installer
# Interactive setup of the metrics collector + API on any Linux host
# (Raspberry Pi, EC2, Lightsail, ...). Run as root:
#
#     sudo ./install.sh
#
# Re-running is safe (idempotent): it re-deploys code and re-applies config.
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
PREFIX="/opt/marnarmon"          # code + venv live here
CONFIG_DIR="/etc/marnarmon"
CONFIG_FILE="${CONFIG_DIR}/config.yml"
DB_DIR="/var/lib/marnarmon"
DB_PATH="${DB_DIR}/metrics.db"
SERVICE_USER="marnarmon"
SYSTEMD_DIR="/etc/systemd/system"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/host"

# Colours (no-op if not a tty)
if [ -t 1 ]; then
    BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; CYAN="\033[36m"; RESET="\033[0m"
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi

info()  { echo -e "${CYAN}==>${RESET} $*"; }
ok()    { echo -e "${GREEN}  ✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}  !${RESET} $*"; }
err()   { echo -e "${RED}  ✗${RESET} $*" >&2; }
ask()   { local p="$1" d="${2:-}" v; if [ -n "$d" ]; then read -r -p "$(echo -e "${BOLD}${p}${RESET} [${d}]: ")" v; echo "${v:-$d}"; else read -r -p "$(echo -e "${BOLD}${p}${RESET}: ")" v; echo "$v"; fi; }

# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
if [ "$(id -u)" -ne 0 ]; then
    err "This installer must be run as root. Try: sudo ./install.sh"
    exit 1
fi

if [ ! -d "${SRC_DIR}/marnarmon" ]; then
    err "Cannot find source at ${SRC_DIR}/marnarmon — run install.sh from the repo root."
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    err "systemd (systemctl) not found. This installer targets systemd hosts."
    exit 1
fi

echo -e "${BOLD}MarNarMon host installer${RESET}"
echo "Architecture: $(uname -m)   Kernel: $(uname -r)"
echo

# --------------------------------------------------------------------------- #
# 1. Dependencies
# --------------------------------------------------------------------------- #
install_packages() {
    info "Installing system dependencies (python3, venv, pip)"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip >/dev/null
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q python3 python3-pip >/dev/null
    elif command -v yum >/dev/null 2>&1; then
        yum install -y -q python3 python3-pip >/dev/null
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 py3-pip >/dev/null
    else
        warn "No known package manager found; assuming python3 + venv are present."
    fi
    ok "Dependencies ready ($(python3 --version 2>&1))"
}
install_packages

# --------------------------------------------------------------------------- #
# 2. Service user
# --------------------------------------------------------------------------- #
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
    info "Creating system user '${SERVICE_USER}'"
    useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}" 2>/dev/null \
        || useradd --system --no-create-home --shell /sbin/nologin "${SERVICE_USER}"
    ok "User created"
else
    ok "User '${SERVICE_USER}' already exists"
fi

# --------------------------------------------------------------------------- #
# 3. Interactive configuration
# --------------------------------------------------------------------------- #
echo
info "Configuration"

HOST_NAME="$(ask 'Friendly host name' "$(hostname)")"
INTERVAL="$(ask 'Collection interval in minutes' '5')"
RETENTION="$(ask 'History retention in days' '30')"
API_HOST="$(ask 'API bind address (0.0.0.0 = LAN, 127.0.0.1 = local only)' '0.0.0.0')"
API_PORT="$(ask 'API port' '8787')"

# Validate numerics
for pair in "interval:$INTERVAL" "retention:$RETENTION" "port:$API_PORT"; do
    name="${pair%%:*}"; val="${pair##*:}"
    if ! [[ "$val" =~ ^[0-9]+$ ]]; then err "Invalid ${name}: '${val}' is not a number"; exit 1; fi
done

# Token
API_TOKEN=""
enable_token="$(ask 'Enable bearer-token auth on the API? (y/N)' 'N')"
case "$enable_token" in
    [yY]*)
        if command -v openssl >/dev/null 2>&1; then
            API_TOKEN="$(openssl rand -hex 24)"
        else
            API_TOKEN="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        fi
        ok "Generated API token (shown again at the end)"
        ;;
    *) warn "API will be served WITHOUT authentication" ;;
esac

# --------------------------------------------------------------------------- #
# 4. Disk selection from /etc/fstab
# --------------------------------------------------------------------------- #
echo
info "Selecting disks to monitor (from /etc/fstab)"

# Collect candidate mount points: field 2 of fstab, excluding swap/special.
mapfile -t FSTAB_MOUNTS < <(
    awk '$0 !~ /^[[:space:]]*#/ && NF>=3 {
            mp=$2; type=$3;
            if (mp ~ /^\// && mp!="none" &&
                type !~ /^(swap|proc|sysfs|devpts|tmpfs|devtmpfs|cgroup|cgroup2|debugfs|securityfs|pstore|mqueue|hugetlbfs|configfs|binfmt_misc|autofs|rpc_pipefs|fusectl|efivarfs)$/)
                print mp
         }' /etc/fstab 2>/dev/null | awk '!seen[$0]++'
)

# Always offer "/" even if fstab omits it (some cloud images use root via cmdline).
have_root=0
for m in "${FSTAB_MOUNTS[@]}"; do [ "$m" = "/" ] && have_root=1; done
if [ "$have_root" -eq 0 ]; then FSTAB_MOUNTS=("/" "${FSTAB_MOUNTS[@]}"); fi

if [ "${#FSTAB_MOUNTS[@]}" -eq 0 ]; then
    warn "No mount points found in /etc/fstab; defaulting to '/'"
    FSTAB_MOUNTS=("/")
fi

echo "Available mount points:"
i=1
for m in "${FSTAB_MOUNTS[@]}"; do
    if usage="$(df -h --output=size,used,avail,pcent "$m" 2>/dev/null | tail -1)"; then
        printf "  ${BOLD}%2d${RESET}) %-20s %s\n" "$i" "$m" "$usage"
    else
        printf "  ${BOLD}%2d${RESET}) %-20s ${YELLOW}(not currently mounted)${RESET}\n" "$i" "$m"
    fi
    i=$((i+1))
done

echo
sel="$(ask 'Enter numbers to track (e.g. 1 3), or "all"' 'all')"

SELECTED=()
if [[ "$sel" =~ ^[Aa][Ll][Ll]$ ]]; then
    SELECTED=("${FSTAB_MOUNTS[@]}")
else
    # split on spaces/commas
    for tok in ${sel//,/ }; do
        if [[ "$tok" =~ ^[0-9]+$ ]] && [ "$tok" -ge 1 ] && [ "$tok" -le "${#FSTAB_MOUNTS[@]}" ]; then
            SELECTED+=("${FSTAB_MOUNTS[$((tok-1))]}")
        else
            warn "Ignoring invalid selection: '$tok'"
        fi
    done
fi
[ "${#SELECTED[@]}" -eq 0 ] && SELECTED=("/")
ok "Tracking: ${SELECTED[*]}"

# --------------------------------------------------------------------------- #
# 5. Deploy code + venv
# --------------------------------------------------------------------------- #
echo
info "Deploying application to ${PREFIX}"
mkdir -p "${PREFIX}"
rm -rf "${PREFIX}/marnarmon"
cp -r "${SRC_DIR}/marnarmon" "${PREFIX}/marnarmon"
cp "${SRC_DIR}/requirements.txt" "${PREFIX}/requirements.txt"

if [ ! -d "${PREFIX}/venv" ]; then
    python3 -m venv "${PREFIX}/venv"
fi
"${PREFIX}/venv/bin/pip" install --quiet --upgrade pip >/dev/null
"${PREFIX}/venv/bin/pip" install --quiet -r "${PREFIX}/requirements.txt"
ok "Virtualenv ready with dependencies"

mkdir -p "${DB_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}" "${DB_DIR}"

# --------------------------------------------------------------------------- #
# 6. Write config
# --------------------------------------------------------------------------- #
info "Writing ${CONFIG_FILE}"
mkdir -p "${CONFIG_DIR}"
{
    echo "# MarNarMon config — generated by install.sh on $(date -Is)"
    echo "host:"
    echo "  name: \"${HOST_NAME}\""
    echo "collection:"
    echo "  interval_minutes: ${INTERVAL}"
    echo "  retention_days: ${RETENTION}"
    echo "database:"
    echo "  path: ${DB_PATH}"
    echo "network:"
    echo "  interfaces: []"
    echo "disks:"
    for m in "${SELECTED[@]}"; do echo "  - ${m}"; done
    echo "api:"
    echo "  host: \"${API_HOST}\""
    echo "  port: ${API_PORT}"
    echo "  token: \"${API_TOKEN}\""
    echo "  default_history_minutes: 1440"
} > "${CONFIG_FILE}"
chown root:"${SERVICE_USER}" "${CONFIG_FILE}"
chmod 640 "${CONFIG_FILE}"
ok "Config written"

# --------------------------------------------------------------------------- #
# 7. Install systemd units
# --------------------------------------------------------------------------- #
info "Installing systemd units"
render_unit() {
    sed -e "s|__PREFIX__|${PREFIX}|g" \
        -e "s|__USER__|${SERVICE_USER}|g" \
        -e "s|__DB_DIR__|${DB_DIR}|g" \
        -e "s|__INTERVAL__|${INTERVAL}|g" \
        -e "s|__API_HOST__|${API_HOST}|g" \
        -e "s|__API_PORT__|${API_PORT}|g" \
        "$1" > "${SYSTEMD_DIR}/$(basename "$1")"
}
render_unit "${SRC_DIR}/systemd/marnarmon-collector.service"
render_unit "${SRC_DIR}/systemd/marnarmon-collector.timer"
render_unit "${SRC_DIR}/systemd/marnarmon-api.service"

systemctl daemon-reload
systemctl enable --now marnarmon-collector.timer >/dev/null 2>&1
systemctl enable --now marnarmon-api.service >/dev/null 2>&1
ok "Units installed and enabled"

# --------------------------------------------------------------------------- #
# 8. First collection + self-check
# --------------------------------------------------------------------------- #
echo
info "Running first collection cycle"
if sudo -u "${SERVICE_USER}" MARNARMON_CONFIG="${CONFIG_FILE}" \
        "${PREFIX}/venv/bin/python" -m marnarmon.collect; then
    ok "Collector ran successfully"
else
    err "Collector failed — check: journalctl -u marnarmon-collector.service"
fi

info "Checking API health"
sleep 2
auth_header=()
[ -n "$API_TOKEN" ] && auth_header=(-H "Authorization: Bearer ${API_TOKEN}")
check_host="$API_HOST"; [ "$check_host" = "0.0.0.0" ] && check_host="127.0.0.1"
if command -v curl >/dev/null 2>&1; then
    if curl -fsS "${auth_header[@]}" "http://${check_host}:${API_PORT}/health" >/dev/null 2>&1; then
        ok "API is responding at http://${check_host}:${API_PORT}/health"
    else
        warn "API not responding yet — check: journalctl -u marnarmon-api.service"
    fi
else
    warn "curl not installed; skipping API check"
fi

# --------------------------------------------------------------------------- #
# Done
# --------------------------------------------------------------------------- #
echo
echo -e "${GREEN}${BOLD}MarNarMon installed.${RESET}"
echo "  API:        http://${check_host}:${API_PORT}"
echo "  Endpoints:  /health  /metrics/current  /metrics/history?window=24h"
echo "  Config:     ${CONFIG_FILE}"
echo "  Database:   ${DB_PATH}"
echo "  Collector:  every ${INTERVAL} min (systemctl status marnarmon-collector.timer)"
if [ -n "$API_TOKEN" ]; then
    echo
    echo -e "  ${BOLD}API token:${RESET} ${API_TOKEN}"
    echo "  Send header:  Authorization: Bearer ${API_TOKEN}"
fi
echo
echo "  Logs:   journalctl -u marnarmon-api.service -f"
echo "          journalctl -u marnarmon-collector.service -f"
echo "  Remove: sudo ./uninstall.sh"
