#!/usr/bin/env bash
#
# MarNarMon host uninstaller. Run as root: sudo ./uninstall.sh
#
set -euo pipefail

PREFIX="/opt/marnarmon"
CONFIG_DIR="/etc/marnarmon"
DB_DIR="/var/lib/marnarmon"
SERVICE_USER="marnarmon"
SYSTEMD_DIR="/etc/systemd/system"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo ./uninstall.sh" >&2
    exit 1
fi

echo "Stopping and disabling services..."
systemctl disable --now marnarmon-collector.timer 2>/dev/null || true
systemctl disable --now marnarmon-collector.service 2>/dev/null || true
systemctl disable --now marnarmon-api.service 2>/dev/null || true

rm -f "${SYSTEMD_DIR}/marnarmon-collector.timer" \
      "${SYSTEMD_DIR}/marnarmon-collector.service" \
      "${SYSTEMD_DIR}/marnarmon-api.service"
systemctl daemon-reload

echo "Removing application files..."
rm -rf "${PREFIX}"

read -r -p "Delete config (${CONFIG_DIR})? [y/N]: " del_cfg
case "$del_cfg" in [yY]*) rm -rf "${CONFIG_DIR}";; esac

read -r -p "Delete metrics database (${DB_DIR})? [y/N]: " del_db
case "$del_db" in [yY]*) rm -rf "${DB_DIR}";; esac

read -r -p "Remove system user '${SERVICE_USER}'? [y/N]: " del_user
case "$del_user" in [yY]*) userdel "${SERVICE_USER}" 2>/dev/null || true;; esac

echo "MarNarMon removed."
