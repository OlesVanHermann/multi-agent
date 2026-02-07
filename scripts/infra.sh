#!/bin/bash
# infra.sh - Start/stop infrastructure + Architect (agent 000)
# Usage: ./scripts/infra.sh start    # Docker, Redis, Keycloak, Dashboard, Agent 000
#        ./scripts/infra.sh stop     # Stop everything

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
BRIDGE_SCRIPT="$BASE_DIR/core/agent-bridge/agent.py"
LOG_DIR="$BASE_DIR/logs/000"
WEB_DIR="$BASE_DIR/web"

# Auto-detect MA_PREFIX from project-config.md if not set
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"
SESSION_NAME="${MA_PREFIX}-agent-000"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Docker helper ──

setup_docker() {
    log_info "Checking Docker..."
    if ! command -v docker &>/dev/null; then
        log_info "Docker not found. Installing..."
        if command -v brew &>/dev/null; then
            brew install --cask docker
            log_info "Docker Desktop installed. Please launch it from Applications, then re-run."
            exit 1
        elif command -v apt-get &>/dev/null; then
            sudo apt-get update -qq && sudo apt-get install -y -qq docker.io docker-compose-plugin
            sudo systemctl start docker
            sudo usermod -aG docker "$USER"
            log_ok "Docker installed"
        else
            log_error "Cannot install Docker automatically. Install Docker manually."
            exit 1
        fi
    fi

    DOCKER="docker"
    if ! docker info &>/dev/null 2>&1; then
        if sudo docker info &>/dev/null 2>&1; then
            DOCKER="sudo docker"
            log_warn "Using sudo for Docker (add user to docker group: sudo usermod -aG docker \$USER)"
        else
            log_error "Docker not running. Start Docker Desktop (Mac) or 'sudo systemctl start docker' (Linux)."
            exit 1
        fi
    fi
    log_ok "Docker ready"
}

# ── Start ──

do_start() {
    mkdir -p "$LOG_DIR"
    setup_docker

    # Redis
    log_info "Starting Redis..."
    if redis-cli ping &>/dev/null 2>&1; then
        log_ok "Redis already running"
    else
        $DOCKER run -d --name ma-redis -p 127.0.0.1:6379:6379 \
            -v ma-redis-data:/data --restart unless-stopped \
            redis:7-alpine redis-server --appendonly yes 2>/dev/null \
            || $DOCKER start ma-redis 2>/dev/null || true
        sleep 2
        if redis-cli ping &>/dev/null 2>&1; then
            log_ok "Redis started (Docker)"
        else
            log_error "Failed to start Redis"
            exit 1
        fi
    fi

    # Keycloak
    log_info "Starting Keycloak..."
    if $DOCKER ps --format '{{.Names}}' | grep -q ma-keycloak; then
        log_ok "Keycloak already running"
    else
        REALM_FILE="$WEB_DIR/keycloak/realm-multi-agent.json"
        REALM_MOUNT=""
        if [ -f "$REALM_FILE" ]; then
            REALM_MOUNT="-v $REALM_FILE:/opt/keycloak/data/import/realm-multi-agent.json:ro"
        fi
        $DOCKER run -d --name ma-keycloak -p 127.0.0.1:8080:8080 \
            -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \
            -e KC_HEALTH_ENABLED=true \
            $REALM_MOUNT \
            -v ma-keycloak-data:/opt/keycloak/data \
            --restart unless-stopped \
            quay.io/keycloak/keycloak:23.0 start-dev --import-realm 2>/dev/null \
            || $DOCKER start ma-keycloak 2>/dev/null || true
        log_ok "Keycloak starting on http://localhost:8080"
    fi

    # Web Dashboard
    log_info "Starting web dashboard..."
    if lsof -i :8000 &>/dev/null 2>&1; then
        log_ok "Dashboard already running on :8000"
    else
        # Install Python deps if needed
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

    # Agent 000
    log_info "Starting agent-000..."
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_warn "Session $SESSION_NAME already exists. Attach with: tmux attach -t $SESSION_NAME"
    else
        tmux new-session -d -s "$SESSION_NAME"
        tmux send-keys -t "$SESSION_NAME" "cd '$BASE_DIR' && claude" Enter
        sleep 2
        tmux new-window -t "$SESSION_NAME" -n bridge
        tmux send-keys -t "$SESSION_NAME:bridge" "cd '$BASE_DIR' && sleep 3 && MA_PREFIX=$MA_PREFIX python3 '$BRIDGE_SCRIPT' 000 2>&1 | tee -a '$LOG_DIR/bridge.log'" Enter
        tmux select-window -t "$SESSION_NAME:0"
        log_ok "Agent 000 started in tmux session: $SESSION_NAME"
    fi

    # Summary
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}   INFRASTRUCTURE READY${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  Redis:     $(redis-cli ping 2>/dev/null || echo 'NOT RUNNING')"
    echo "  Dashboard: http://localhost:8000"
    echo "  Agent 000: tmux attach -t $SESSION_NAME"
    echo ""
    echo "  Stop:      ./scripts/infra.sh stop"
    echo "  Agents:    ./scripts/agent.sh start all"
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
}

# ── Stop ──

do_stop() {
    # Stop all worker agents first
    "$SCRIPT_DIR/agent.sh" stop all

    # Docker
    DOCKER="docker"
    if ! docker info &>/dev/null 2>&1; then
        if sudo docker info &>/dev/null 2>&1; then
            DOCKER="sudo docker"
        fi
    fi

    # Agent 000
    log_info "Stopping agent-000..."
    if tmux kill-session -t "$SESSION_NAME" 2>/dev/null; then
        log_ok "Killed tmux session $SESSION_NAME"
    else
        log_warn "Session $SESSION_NAME not found"
    fi

    # Dashboard
    log_info "Stopping web dashboard..."
    if [ -f "$LOG_DIR/dashboard.pid" ]; then
        PID=$(cat "$LOG_DIR/dashboard.pid")
        if kill "$PID" 2>/dev/null; then
            log_ok "Killed dashboard (PID: $PID)"
        fi
        mv "$LOG_DIR/dashboard.pid" "$LOG_DIR/dashboard.pid.old" 2>/dev/null || true
    fi
    pkill -f "uvicorn server:app" 2>/dev/null && log_ok "Killed uvicorn processes" || true

    # Keycloak
    log_info "Stopping Keycloak..."
    if $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -q ma-keycloak; then
        $DOCKER stop ma-keycloak 2>/dev/null && log_ok "Keycloak stopped"
    else
        log_warn "Keycloak not running"
    fi

    # Redis
    log_info "Stopping Redis..."
    if $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -q ma-redis; then
        $DOCKER stop ma-redis 2>/dev/null && log_ok "Redis stopped"
    else
        log_warn "Redis container not running"
    fi

    echo ""
    log_ok "Infrastructure stopped."
}

# ── Help ──

show_help() {
    echo "Usage: $0 <start|stop>"
    echo ""
    echo "  $0 start   Start Docker, Redis, Keycloak, Dashboard, Agent 000"
    echo "  $0 stop    Stop everything"
}

# ── Main ──

case "$1" in
    start)  do_start ;;
    stop)   do_stop ;;
    -h|--help|help|"") show_help ;;
    *)      log_error "Unknown action: $1"; show_help; exit 1 ;;
esac
