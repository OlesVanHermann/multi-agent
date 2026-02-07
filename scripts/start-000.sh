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
SESSION_NAME="agent-000"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

mkdir -p "$LOG_DIR"

# === 1. Start Redis ===
log_info "Starting Redis..."
if redis-cli ping &>/dev/null 2>&1; then
    log_ok "Redis already running"
else
    if command -v brew &>/dev/null; then
        brew services start redis 2>/dev/null || true
        sleep 2
    elif command -v redis-server &>/dev/null; then
        redis-server --daemonize yes --port 6379
        sleep 1
    else
        log_error "Redis not installed. Run: brew install redis"
        exit 1
    fi

    if redis-cli ping &>/dev/null 2>&1; then
        log_ok "Redis started"
    else
        log_error "Failed to start Redis"
        exit 1
    fi
fi

# === 2. Start Web Dashboard ===
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
    python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 \
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
    tmux send-keys -t "$SESSION_NAME.1" "cd '$BASE_DIR' && sleep 3 && python3 '$BRIDGE_SCRIPT' 000 2>&1 | tee -a '$LOG_DIR/bridge.log'" Enter

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
