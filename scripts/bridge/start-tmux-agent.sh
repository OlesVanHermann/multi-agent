#!/bin/bash
# start-tmux-agent.sh - Start agent with interactive Claude + tmux bridge
# Usage: ./start-tmux-agent.sh <agent_id>    # Start single agent
#        ./start-tmux-agent.sh all           # Start all agents from prompts/
#
# This creates TWO tmux panes per agent:
# - Pane 0: Claude running interactively (with MCP access!)
# - Pane 1: Bridge process monitoring Redis

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/../.."
BRIDGE_SCRIPT="$BASE_DIR/core/agent-bridge/agent-tmux.py"
LOG_DIR="$BASE_DIR/logs"
PROMPTS_DIR="$BASE_DIR/prompts"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Ensure Redis is running
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
    local SESSION_NAME="agent-$agent_id"

    # Check if session exists
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_warn "Session $SESSION_NAME already exists, skipping"
        return
    fi

    # Skip 9XX Architects (they run claude directly, no bridge needed)
    if [[ "$agent_id" =~ ^9[0-9][0-9]$ ]]; then
        log_info "Starting Architect $agent_id (direct claude, no bridge)..."
        tmux new-session -d -s "$SESSION_NAME" -x 200 -y 50 \
            "cd '$BASE_DIR' && claude; echo 'Session ended. Press Enter.'; read"
        log_ok "Architect $agent_id started: $SESSION_NAME"
        return
    fi

    log_info "Starting agent $agent_id with interactive Claude + bridge..."

    mkdir -p "$LOG_DIR/$agent_id"

    # Create tmux session with Claude in main pane
    tmux new-session -d -s "$SESSION_NAME" -x 200 -y 50

    # Pane 0: Claude interactive
    tmux send-keys -t "$SESSION_NAME" "cd '$BASE_DIR' && claude" Enter

    # Wait for Claude to start
    sleep 2

    # Split window horizontally - Pane 1: Bridge process
    tmux split-window -t "$SESSION_NAME" -h -p 30

    # Pane 1: Bridge (monitors Redis, sends to Claude via tmux)
    tmux send-keys -t "$SESSION_NAME.1" "cd '$BASE_DIR' && sleep 3 && python3 '$BRIDGE_SCRIPT' $agent_id 2>&1 | tee -a '$LOG_DIR/$agent_id/bridge.log'" Enter

    # Select pane 0 (Claude) as active
    tmux select-pane -t "$SESSION_NAME.0"

    log_ok "Agent $agent_id started: $SESSION_NAME"
}

start_all() {
    log_info "Auto-detecting agents from prompts/..."

    # Find all prompt files and extract agent IDs
    local count=0
    for prompt_file in "$PROMPTS_DIR"/[0-9][0-9][0-9]-*.md; do
        [ -f "$prompt_file" ] || continue
        filename=$(basename "$prompt_file" .md)
        agent_id="${filename%%-*}"

        start_single_agent "$agent_id"
        count=$((count + 1))

        # Small delay between starts to avoid overwhelming the system
        sleep 1
    done

    echo ""
    log_ok "Started $count agents"
    echo ""
    echo "  List sessions: tmux ls | grep agent"
    echo "  Attach: tmux attach -t agent-300"
    echo "  Monitor: python3 scripts/bridge/monitor.py"
}

show_help() {
    echo "Usage: $0 <agent_id|all>"
    echo ""
    echo "Examples:"
    echo "  $0 300     # Start agent 300 (interactive Claude + bridge)"
    echo "  $0 all     # Start all agents from prompts/"
    echo ""
    echo "Each agent gets a tmux session with 2 panes:"
    echo "  - Pane 0 (left):  Claude interactive (MCP enabled!)"
    echo "  - Pane 1 (right): Bridge (Redis communication)"
}

# === MAIN ===
ensure_redis

case "$1" in
    "")
        show_help
        exit 1
        ;;
    "all")
        start_all
        ;;
    "-h"|"--help"|"help")
        show_help
        ;;
    *)
        start_single_agent "$1"
        echo ""
        echo "  Attach: tmux attach -t agent-$1"
        echo "  Monitor: python3 scripts/bridge/monitor.py"
        ;;
esac
