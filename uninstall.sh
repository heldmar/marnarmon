#!/usr/bin/env bash
#
# ServerMon host uninstaller. Run as root: sudo ./uninstall.sh
#
set -euo pipefail

PREFIX="/opt/servermon"
CONFIG_DIR="/etc/servermon"
DB_DIR="/var/lib/servermon"
SERVICE_USER="servermon"
SYSTEMD_DIR="/etc/systemd/system"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo ./uninstall.sh" >&2
    exit 1
fi

echo "Stopping and disabling services..."
systemctl disable --now servermon-collector.timer 2>/dev/null || true
systemctl disable --now servermon-collector.service 2>/dev/null || true
systemctl disable --now servermon-api.service 2>/dev/null || true

rm -f "${SYSTEMD_DIR}/servermon-collector.timer" \
      "${SYSTEMD_DIR}/servermon-collector.service" \
      "${SYSTEMD_DIR}/servermon-api.service"
systemctl daemon-reload

echo "Removing application files..."
rm -rf "${PREFIX}"

read -r -p "Delete config (${CONFIG_DIR})? [y/N]: " del_cfg
case "$del_cfg" in [yY]*) rm -rf "${CONFIG_DIR}";; esac

read -r -p "Delete metrics database (${DB_DIR})? [y/N]: " del_db
case "$del_db" in [yY]*) rm -rf "${DB_DIR}";; esac

read -r -p "Remove system user '${SERVICE_USER}'? [y/N]: " del_user
case "$del_user" in [yY]*) userdel "${SERVICE_USER}" 2>/dev/null || true;; esac

echo "ServerMon removed."
