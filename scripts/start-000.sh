#!/bin/bash
# start-000.sh - Start Architect (agent 000) with full infrastructure
# Usage: ./scripts/start-000.sh
#
# This script:
# 1. Starts Redis (brew services)
# 2. Starts the web dashboard (uvicorn in background)
# 3. Creates tmux session agent-000 with Claude + bridge

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
BRIDGE_SCRIPT="$BASE_DIR/core/agent-bridge/agent.py"
LOG_DIR="$BASE_DIR/logs/000"
WEB_DIR="$BASE_DIR/web"
MA_PREFIX="${MA_PREFIX:-ma}"
SESSION_NAME="${MA_PREFIX}-agent-000"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

mkdir -p "$LOG_DIR"

# === Detect mode: Docker or Native ===
USE_DOCKER=false
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    USE_DOCKER=true
fi

# === 1. Start Redis ===
log_info "Starting Redis..."
if redis-cli ping &>/dev/null 2>&1; then
    log_ok "Redis already running"
elif $USE_DOCKER; then
    log_info "Starting Redis via Docker..."
    docker run -d --name ma-redis -p 127.0.0.1:6379:6379 \
        -v ma-redis-data:/data --restart unless-stopped \
        redis:7-alpine redis-server --appendonly yes 2>/dev/null \
        || docker start ma-redis 2>/dev/null || true
    sleep 2
    redis-cli ping &>/dev/null && log_ok "Redis started (Docker)" || log_error "Failed to start Redis"
elif command -v brew &>/dev/null; then
    brew services start redis 2>/dev/null || true
    sleep 2
    redis-cli ping &>/dev/null && log_ok "Redis started (brew)" || log_error "Failed to start Redis"
elif command -v redis-server &>/dev/null; then
    redis-server --daemonize yes --port 6379
    sleep 1
    redis-cli ping &>/dev/null && log_ok "Redis started (native)" || log_error "Failed to start Redis"
else
    log_error "Redis not installed. Install redis or docker."
    exit 1
fi

# === 2. Start Keycloak (Docker only) ===
if $USE_DOCKER && [ -f "$WEB_DIR/keycloak/realm-multi-agent.json" ]; then
    log_info "Starting Keycloak..."
    if docker ps --format '{{.Names}}' | grep -q ma-keycloak; then
        log_ok "Keycloak already running"
    else
        docker run -d --name ma-keycloak -p 127.0.0.1:8080:8080 \
            -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \
            -e KC_HEALTH_ENABLED=true \
            -v "$WEB_DIR/keycloak/realm-multi-agent.json:/opt/keycloak/data/import/realm-multi-agent.json:ro" \
            -v ma-keycloak-data:/opt/keycloak/data \
            --restart unless-stopped \
            quay.io/keycloak/keycloak:23.0 start-dev --import-realm 2>/dev/null \
            || docker start ma-keycloak 2>/dev/null || true
        log_ok "Keycloak starting on http://localhost:8080"
    fi
else
    log_warn "Keycloak skipped (no Docker or no realm config)"
fi

# === 3. Start Web Dashboard ===
log_info "Starting web dashboard..."
if lsof -i :8000 &>/dev/null 2>&1; then
    log_ok "Dashboard already running on :8000"
else
    # Install Python deps if needed
    if ! python3 -c "import fastapi" 2>/dev/null; then
        log_info "Installing Python dependencies..."
        pip3 install -r "$WEB_DIR/backend/requirements.txt" 2>/dev/null
    fi

    # Start uvicorn in background
    cd "$WEB_DIR/backend"
    MA_PREFIX=$MA_PREFIX python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 \
        >> "$LOG_DIR/dashboard.log" 2>&1 &
    DASHBOARD_PID=$!
    echo "$DASHBOARD_PID" > "$LOG_DIR/dashboard.pid"
    cd "$BASE_DIR"
    sleep 2

    if lsof -i :8000 &>/dev/null 2>&1; then
        log_ok "Dashboard started on http://localhost:8000 (PID: $DASHBOARD_PID)"
    else
        log_warn "Dashboard may not have started. Check $LOG_DIR/dashboard.log"
    fi
fi

# === 3. Start Agent 000 tmux session ===
log_info "Starting agent-000..."
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    log_warn "Session $SESSION_NAME already exists. Attach with: tmux attach -t $SESSION_NAME"
else
    # Create tmux session with Claude in main pane
    tmux new-session -d -s "$SESSION_NAME" -x 200 -y 50

    # Pane 0: Claude interactive
    tmux send-keys -t "$SESSION_NAME" "cd '$BASE_DIR' && claude" Enter

    # Wait for Claude to start
    sleep 2

    # Split window horizontally - Pane 1: Bridge process
    tmux split-window -t "$SESSION_NAME" -h -p 30

    # Pane 1: Bridge (monitors Redis, sends to Claude via tmux)
    tmux send-keys -t "$SESSION_NAME.1" "cd '$BASE_DIR' && sleep 3 && MA_PREFIX=$MA_PREFIX python3 '$BRIDGE_SCRIPT' 000 2>&1 | tee -a '$LOG_DIR/bridge.log'" Enter

    # Select pane 0 (Claude) as active
    tmux select-pane -t "$SESSION_NAME.0"

    log_ok "Agent 000 started in tmux session: $SESSION_NAME"
fi

# === Summary ===
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   ARCHITECT (000) - INFRASTRUCTURE READY${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Redis:     $(redis-cli ping 2>/dev/null || echo 'NOT RUNNING')"
echo "  Dashboard: http://localhost:8000"
echo "  Agent 000: tmux attach -t $SESSION_NAME"
echo ""
echo "  Stop:      ./scripts/stop-000.sh"
echo "  Start all: ./scripts/start.sh all"
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
