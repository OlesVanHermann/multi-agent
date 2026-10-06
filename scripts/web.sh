#!/bin/bash
# web.sh - Start/stop web dashboard (backend + frontend build)
# Usage: ./scripts/web.sh start     # Build frontend (if needed) + start uvicorn
#        ./scripts/web.sh stop      # Stop uvicorn
#        ./scripts/web.sh rebuild   # Stop + force rebuild frontend + start

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
if [ -f "$BASE_DIR/setup/secrets.cfg" ]; then
    set -a
    eval "$(grep -E '^[A-Z_]+=' "$BASE_DIR/setup/secrets.cfg" | grep -v '^#')"
    set +a
else
    # Garde-fou : sans secrets.cfg le backend démarre mais rien ne marche
    # (Redis NOAUTH, ws-ticket 503). Cas typique : lancé depuis un clone
    # patch (~/multi-agent-git) au lieu du working copy (~/multi-agent).
    echo -e "\033[0;31m[ERROR]\033[0m $BASE_DIR/setup/secrets.cfg absent — mauvais répertoire ?" >&2
    echo "        Lancer depuis le working copy : cd ~/multi-agent && ./scripts/web.sh $1" >&2
    exit 1
fi
WEB_DIR="$BASE_DIR/web"
LOG_DIR="$BASE_DIR/logs/000"
PID_FILE="$LOG_DIR/dashboard.pid"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

do_start() {
    mkdir -p "$LOG_DIR"

    if lsof -iTCP:8050 -sTCP:LISTEN &>/dev/null 2>&1; then
        log_ok "Dashboard already running on :8050"
        return
    fi

    # Python deps
    if ! python3 -c "import fastapi" 2>/dev/null; then
        log_info "Installing Python dependencies..."
        pip3 install -r "$WEB_DIR/backend/requirements.txt" 2>/dev/null || \
        pip3 install --break-system-packages -r "$WEB_DIR/backend/requirements.txt" 2>/dev/null
    fi

    # Build frontend if missing or outdated
    NEED_BUILD=false
    if [ ! -f "$WEB_DIR/frontend/dist/index.html" ]; then
        NEED_BUILD=true
    elif [ -f "$WEB_DIR/frontend/src/App.jsx" ]; then
        NEWEST_SRC=$(find "$WEB_DIR/frontend/src" -type f -newer "$WEB_DIR/frontend/dist/index.html" 2>/dev/null | head -1)
        [ -n "$NEWEST_SRC" ] && NEED_BUILD=true
    fi

    if $NEED_BUILD; then
        if command -v npm &>/dev/null; then
            log_info "Building frontend..."
            cd "$WEB_DIR/frontend"
            npm install --silent 2>/dev/null
            npm run build 2>/dev/null
            cd "$BASE_DIR"
            log_ok "Frontend built"
        else
            log_warn "npm not found — frontend not built (API-only mode)"
        fi
    fi

    # Start uvicorn
    log_info "Starting dashboard..."
    cd "$WEB_DIR/backend"
        python3 -m uvicorn multi_agent.backend:app --host 127.0.0.1 --port 8050 \
        --ws-ping-interval 25 --ws-ping-timeout 90 \
        >> "$LOG_DIR/dashboard.log" 2>&1 &
    DASHBOARD_PID=$!
    echo "$DASHBOARD_PID" > "$PID_FILE"
    cd "$BASE_DIR"
    sleep 2

    if lsof -iTCP:8050 -sTCP:LISTEN &>/dev/null 2>&1; then
        log_ok "Dashboard started on http://127.0.0.1:8050 (PID: $DASHBOARD_PID)"
    else
        log_warn "Dashboard may not have started. Check $LOG_DIR/dashboard.log"
    fi
}

do_stop() {
    log_info "Stopping web dashboard..."
    # 1. Kill by PID file
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill "$PID" 2>/dev/null; then
            log_ok "Killed dashboard (PID: $PID)"
        fi
        mv "$PID_FILE" "$PID_FILE.old" 2>/dev/null || true
    fi
    # 2. Force-kill all uvicorn processes (SIGKILL — graceful shutdown hangs on open WebSocket connections)
    pkill -9 -f "uvicorn multi_agent.backend:app" 2>/dev/null && log_ok "Killed uvicorn processes" || true
    # 3. Force-kill anything still holding port 8050 (safety net)
    local pids
    pids=$(lsof -ti:8050 2>/dev/null || true)
    if [ -n "$pids" ]; then
        kill -9 $pids 2>/dev/null && log_ok "Force-killed stale processes on :8050" || true
    fi
    sleep 1
}

do_rebuild() {
    do_stop
    sleep 1
    log_info "Force rebuilding frontend..."
    if command -v npm &>/dev/null; then
        cd "$WEB_DIR/frontend"
        rm -rf dist
        npm install --silent 2>/dev/null
        npm run build 2>/dev/null
        cd "$BASE_DIR"
        log_ok "Frontend rebuilt"
    else
        log_error "npm not found — cannot build frontend"
        exit 1
    fi
    do_start
}

show_help() {
    echo "Usage: $0 <start|stop|rebuild>"
    echo ""
    echo "  $0 start     Build frontend (if needed) + start uvicorn on :8050"
    echo "  $0 stop      Stop uvicorn"
    echo "  $0 rebuild   Stop + force rebuild frontend + start"
}

case "$1" in
    start)   do_start ;;
    stop)    do_stop ;;
    rebuild) do_rebuild ;;
    -h|--help|help|"") show_help ;;
    *)      log_error "Unknown action: $1"; show_help; exit 1 ;;
esac
