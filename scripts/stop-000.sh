#!/bin/bash
# stop-000.sh - Stop Architect (agent 000) and infrastructure
# Usage: ./scripts/stop-000.sh
#
# This script:
# 1. Kills tmux session agent-000
# 2. Stops the web dashboard (uvicorn)
# 3. Stops Redis (brew services)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
LOG_DIR="$BASE_DIR/logs/000"
MA_PREFIX="${MA_PREFIX:-ma}"
SESSION_NAME="${MA_PREFIX}-agent-000"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log_info() { echo -e "[INFO] $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# === 1. Kill agent-000 tmux session ===
log_info "Stopping agent-000..."
if tmux kill-session -t "$SESSION_NAME" 2>/dev/null; then
    log_ok "Killed tmux session $SESSION_NAME"
else
    log_warn "Session $SESSION_NAME not found"
fi

# === 2. Stop web dashboard ===
log_info "Stopping web dashboard..."
if [ -f "$LOG_DIR/dashboard.pid" ]; then
    PID=$(cat "$LOG_DIR/dashboard.pid")
    if kill "$PID" 2>/dev/null; then
        log_ok "Killed dashboard (PID: $PID)"
    fi
    mv "$LOG_DIR/dashboard.pid" "$LOG_DIR/dashboard.pid.old" 2>/dev/null || true
fi
# Also kill any remaining uvicorn on port 8000
pkill -f "uvicorn server:app" 2>/dev/null && log_ok "Killed uvicorn processes" || true

# === 3. Stop Keycloak (Docker) ===
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q ma-keycloak; then
    log_info "Stopping Keycloak..."
    docker stop ma-keycloak 2>/dev/null && log_ok "Keycloak stopped" || true
fi

# === 4. Stop Redis ===
log_info "Stopping Redis..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q ma-redis; then
    docker stop ma-redis 2>/dev/null && log_ok "Redis stopped (Docker)" || true
elif command -v brew &>/dev/null; then
    brew services stop redis 2>/dev/null && log_ok "Redis stopped (brew)" || true
else
    redis-cli shutdown 2>/dev/null && log_ok "Redis stopped" || true
fi

echo ""
log_ok "Architect (000) and infrastructure stopped."
