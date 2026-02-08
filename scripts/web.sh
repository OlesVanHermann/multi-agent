#!/bin/bash
# web.sh - Start/stop web dashboard (backend + frontend build)
# Usage: ./scripts/web.sh start     # Build frontend (if needed) + start uvicorn
#        ./scripts/web.sh stop      # Stop uvicorn
#        ./scripts/web.sh rebuild   # Stop + force rebuild frontend + start

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
WEB_DIR="$BASE_DIR/web"
LOG_DIR="$BASE_DIR/logs/000"
PID_FILE="$LOG_DIR/dashboard.pid"

# Auto-detect MA_PREFIX from project-config.md if not set
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

do_start() {
    mkdir -p "$LOG_DIR"

    if lsof -iTCP:8000 -sTCP:LISTEN &>/dev/null 2>&1; then
        log_ok "Dashboard already running on :8000"
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

    # Simple auth fallback (used when Keycloak client is not configured)
    SIMPLE_AUTH="${SIMPLE_AUTH:-octave:changeme:admin,operator:changeme:operator,viewer:changeme:viewer}"

    # Start uvicorn
    log_info "Starting dashboard..."
    cd "$WEB_DIR/backend"
    MA_PREFIX=$MA_PREFIX SIMPLE_AUTH="$SIMPLE_AUTH" \
        python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 \
        >> "$LOG_DIR/dashboard.log" 2>&1 &
    DASHBOARD_PID=$!
    echo "$DASHBOARD_PID" > "$PID_FILE"
    cd "$BASE_DIR"
    sleep 2

    if lsof -iTCP:8000 -sTCP:LISTEN &>/dev/null 2>&1; then
        log_ok "Dashboard started on http://127.0.0.1:8000 (PID: $DASHBOARD_PID)"
    else
        log_warn "Dashboard may not have started. Check $LOG_DIR/dashboard.log"
    fi
}

do_stop() {
    log_info "Stopping web dashboard..."
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill "$PID" 2>/dev/null; then
            log_ok "Killed dashboard (PID: $PID)"
        fi
        mv "$PID_FILE" "$PID_FILE.old" 2>/dev/null || true
    fi
    pkill -f "uvicorn server:app" 2>/dev/null && log_ok "Killed uvicorn processes" || true
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
    echo "  $0 start     Build frontend (if needed) + start uvicorn on :8000"
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
