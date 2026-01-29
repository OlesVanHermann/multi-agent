#!/bin/bash
# start-bridge-agents.sh - Lance des agents avec le nouveau bridge PTY
# Usage: ./start-bridge-agents.sh 300           # Lance agent 300 (interactif)
#        ./start-bridge-agents.sh 300 310       # Lance agents 300-309 (headless tmux)
#        ./start-bridge-agents.sh all           # Lance tous les agents configurés

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/../.."
AGENT_SCRIPT="$BASE_DIR/core/agent-bridge/agent.py"
LOG_DIR="$BASE_DIR/logs"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

# Default agents configuration
AGENTS=(
    "000:Super-Master"
    "100:Master"
    "200:Explorer"
    "300:Developer-Excel"
    "301:Developer-Word"
    "302:Developer-PPTX"
    "303:Developer-PDF"
    "400:Merge"
    "500:Test"
    "600:Release"
)

mkdir -p "$LOG_DIR"

# Claude configuration - needed for API authentication
# Set these environment variables or adjust the defaults below
# Option 1: Set CLAUDE_CONFIG_DIR to your Claude config directory
# Option 2: Use default ~/.claude (standard Claude Code installation)
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CLAUDE_PROFILES_DIR="${CLAUDE_PROFILES_DIR:-}"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

ensure_redis() {
    if ! redis-cli ping &>/dev/null; then
        log_info "Starting Redis..."
        if command -v redis-server &>/dev/null; then
            redis-server --daemonize yes --port 6379
            sleep 1
        else
            log_error "Redis not installed. Please start Redis first."
            exit 1
        fi
    fi
    log_ok "Redis is running"
}

start_single_agent() {
    local agent_id=$1
    local mode=${2:-interactive}

    log_info "Starting agent $agent_id ($mode mode)..."

    if [ "$mode" = "headless" ]; then
        SESSION_NAME="agent-$agent_id"

        # Check if session exists
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            log_warn "Session $SESSION_NAME already exists, skipping"
            return
        fi

        # Start in tmux with Claude environment
        mkdir -p "$LOG_DIR/$agent_id"
        tmux new-session -d -s "$SESSION_NAME" \
            "export CLAUDE_CONFIG_DIR='$CLAUDE_CONFIG_DIR'; \
             export CLAUDE_PROFILES_DIR='$CLAUDE_PROFILES_DIR'; \
             python3 '$AGENT_SCRIPT' $agent_id --headless 2>&1 | tee -a '$LOG_DIR/$agent_id/bridge.log'"

        log_ok "Agent $agent_id started in tmux session: $SESSION_NAME"
    else
        # Interactive mode with Claude environment
        export CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR"
        export CLAUDE_PROFILES_DIR="$CLAUDE_PROFILES_DIR"
        python3 "$AGENT_SCRIPT" "$agent_id"
    fi
}

start_range() {
    local start_id=$1
    local end_id=$2

    log_info "Starting agents $start_id to $((end_id - 1)) in headless mode..."
    echo ""

    for ((i=start_id; i<end_id; i++)); do
        start_single_agent "$i" "headless"
    done

    echo ""
    log_ok "All agents started"
    echo ""
    echo "Commands:"
    echo "  tmux attach -t agent-$start_id    # Attach to agent"
    echo "  tmux ls                           # List sessions"
    echo "  ./stop-bridge-agents.sh           # Stop all"
}

start_all() {
    log_info "Starting all configured agents..."
    echo ""

    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id desc <<< "$agent"
        start_single_agent "$id" "headless"
    done

    echo ""
    log_ok "All agents started"
}

show_help() {
    echo "Usage: $0 <agent_id|start_id end_id|all>"
    echo ""
    echo "Examples:"
    echo "  $0 300           # Start agent 300 (interactive)"
    echo "  $0 300 310       # Start agents 300-309 (headless in tmux)"
    echo "  $0 all           # Start all configured agents"
    echo ""
    echo "Configured agents:"
    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id desc <<< "$agent"
        echo "  $id - $desc"
    done
}

# Main
ensure_redis

case "$1" in
    "")
        show_help
        exit 1
        ;;
    "all")
        start_all
        ;;
    *)
        if [ -n "$2" ]; then
            # Range mode
            start_range "$1" "$2"
        else
            # Single agent (interactive)
            start_single_agent "$1" "interactive"
        fi
        ;;
esac
