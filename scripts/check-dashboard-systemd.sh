#!/bin/bash
# Diagnostic non destructif du sandbox systemd du dashboard.
# Voir patch/HOW_TO_UPGRADE.md — « Dashboard systemd durci ».
set -uo pipefail

SERVICE="${1:-multiagent-dashboard.service}"
REQUIRED=(logs uploads crontab keepalive prompts)
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "SKIP: systemctl absent"
    exit 0
fi
if ! systemctl show "$SERVICE" >/dev/null 2>&1; then
    echo "ERROR: unité $SERVICE introuvable" >&2
    exit 1
fi

protect_home=$(systemctl show "$SERVICE" -p ProtectHome --value)
protect_system=$(systemctl show "$SERVICE" -p ProtectSystem --value)
rw=$(systemctl show "$SERVICE" -p ReadWritePaths --value)
env_files=$(systemctl show "$SERVICE" -p EnvironmentFiles --value)

echo "Service: $SERVICE"
echo "ProtectHome=$protect_home ProtectSystem=$protect_system"

failed=0
if [[ "$env_files" != *"$BASE_DIR/setup/secrets.cfg"* ]]; then
    echo "MISSING EnvironmentFile=$BASE_DIR/setup/secrets.cfg" >&2
    failed=1
fi
for rel in "${REQUIRED[@]}"; do
    path="$BASE_DIR/$rel"
    if [[ " $rw " == *" $path "* || " $rw " == *" $path-"* || " $rw " == *" $path:"* ]]; then
        echo "OK ReadWritePaths=$path"
    else
        echo "MISSING ReadWritePaths=$path" >&2
        failed=1
    fi
done

if [ "$failed" -ne 0 ]; then
    echo "Corriger le drop-in avec setup/multiagent-dashboard-hardening.conf.example" >&2
    exit 1
fi
echo "OK: contrat d'écriture systemd complet"
