#!/bin/bash
# agent.sh - Start/stop agents
# Usage: ./scripts/agent.sh start <agent_id|all>
#        ./scripts/agent.sh stop <agent_id|all>

set -e

# Raise open files limit (each agent = tmux session + claude + bridge)
ulimit -n 10240 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
BRIDGE_SCRIPT="$BASE_DIR/core/agent-bridge/agent.py"
LOG_DIR="$BASE_DIR/logs"
PROMPTS_DIR="$BASE_DIR/prompts"

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

# ── Helpers ──

is_protected() {
    [[ "$1" =~ ^(9[0-9][0-9]|000)$ ]]
}

# ── Start ──

start_single() {
    local agent_id=$1
    local SESSION_NAME="${MA_PREFIX}-agent-$agent_id"

    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_warn "$SESSION_NAME already exists, skipping"
        return
    fi

    if is_protected "$agent_id"; then
        log_warn "Skipping $agent_id (use ./scripts/infra.sh start for Architect)"
        return
    fi

    log_info "Starting agent $agent_id..."
    mkdir -p "$LOG_DIR/$agent_id"

    # Read model: prompts/{agent_id}.model > prompts/default.model
    local MODEL=""
    if [ -f "$PROMPTS_DIR/${agent_id}.model" ]; then
        MODEL=$(cat "$PROMPTS_DIR/${agent_id}.model" | tr -d '[:space:]')
    elif [ -f "$PROMPTS_DIR/default.model" ]; then
        MODEL=$(cat "$PROMPTS_DIR/default.model" | tr -d '[:space:]')
    fi

    tmux new-session -d -s "$SESSION_NAME"
    tmux send-keys -t "$SESSION_NAME" "cd '$BASE_DIR' && claude" Enter
    sleep 4

    # Select model (Enter to type, sleep, Enter to confirm menu)
    if [ -n "$MODEL" ]; then
        tmux send-keys -t "$SESSION_NAME" "/model $MODEL" Enter
        sleep 1
        tmux send-keys -t "$SESSION_NAME" Enter
        sleep 3
    fi

    # Prompt injection is handled by the bridge (agent.py auto-init)

    tmux new-window -t "$SESSION_NAME" -n bridge
    tmux send-keys -t "$SESSION_NAME:bridge" "cd '$BASE_DIR' && sleep 3 && MA_PREFIX=$MA_PREFIX python3 '$BRIDGE_SCRIPT' $agent_id 2>&1 | tee -a '$LOG_DIR/$agent_id/bridge.log'" Enter
    tmux select-window -t "$SESSION_NAME:0"

    log_ok "Agent $agent_id started: $SESSION_NAME"
}

start_all() {
    log_info "Auto-detecting agents from prompts/..."
    local count=0
    for prompt_file in "$PROMPTS_DIR"/[0-9][0-9][0-9]-*.md; do
        [ -f "$prompt_file" ] || continue
        local filename=$(basename "$prompt_file" .md)
        local agent_id="${filename%%-*}"
        start_single "$agent_id"
        count=$((count + 1))
        sleep 1
    done
    echo ""
    log_ok "Started $count agents"
}

ensure_infra() {
    # Check-only: verify infra is up, start ONLY what's missing. Never stop/restart.
    local ok=true

    # Redis
    if ! redis-cli ping &>/dev/null 2>&1; then
        log_error "Redis not running. Start infra first: ./scripts/infra.sh start"
        ok=false
    fi

    # Dashboard
    if ! lsof -iTCP:8000 -sTCP:LISTEN &>/dev/null 2>&1; then
        log_info "Dashboard not running, starting..."
        "$SCRIPT_DIR/web.sh" start
    fi

    # Agent 000
    if ! tmux has-session -t "${MA_PREFIX}-agent-000" 2>/dev/null; then
        log_warn "Agent 000 not running. Start infra first: ./scripts/infra.sh start"
    fi

    if [ "$ok" = false ]; then
        exit 1
    fi
}

do_start() {
    # Check infra is up (no stop/restart, no flush)
    ensure_infra

    local target=$1
    if [ -z "$target" ]; then
        show_help; exit 1
    elif [ "$target" = "all" ]; then
        start_all
    else
        shift
        for agent_id in "$target" "$@"; do
            start_single "$agent_id"
        done
    fi
    echo ""
    echo "  List:   tmux ls | grep ${MA_PREFIX}-agent"
    echo "  Attach: tmux attach -t ${MA_PREFIX}-agent-<id>"
}

# ── Stop ──

stop_single() {
    local agent_id=$1
    local SESSION="${MA_PREFIX}-agent-$agent_id"

    if is_protected "$agent_id"; then
        log_warn "Cannot stop $agent_id (use ./scripts/infra.sh stop)"
        return 1
    fi

    if tmux kill-session -t "$SESSION" 2>/dev/null; then
        log_ok "Killed $SESSION"
    else
        log_warn "$SESSION not found"
    fi
}

stop_all() {
    log_info "Stopping agents (000 and 9XX are NEVER stopped)..."
    tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | cut -d: -f1 | while read session; do
        local agent_id="${session#${MA_PREFIX}-agent-}"
        if is_protected "$agent_id"; then
            log_warn "Skipping $session (protected)"
            continue
        fi
        tmux kill-session -t "$session" 2>/dev/null && log_ok "Killed $session"
    done

    # Update Redis status
    for key in $(redis-cli KEYS "${MA_PREFIX}:agent:*" 2>/dev/null | grep -E "^${MA_PREFIX}:agent:[0-9]+$"); do
        redis-cli HSET "$key" status "stopped" > /dev/null 2>&1
    done
}

do_stop() {
    local target=$1
    if [ -z "$target" ]; then
        show_help; exit 1
    elif [ "$target" = "all" ]; then
        stop_all
    else
        shift
        for agent_id in "$target" "$@"; do
            stop_single "$agent_id"
        done
    fi
    log_ok "Done"
}

# ── Help ──

show_help() {
    echo "Usage: $0 <start|stop> <agent_id|all>"
    echo ""
    echo "  $0 start 300       Start agent 300"
    echo "  $0 start 300 301   Start agents 300 and 301"
    echo "  $0 start all       Start all agents from prompts/"
    echo "  $0 stop 300        Stop agent 300"
    echo "  $0 stop all        Stop all (except 000 and 9XX)"
    echo ""
    echo "  000 and 9XX are protected — use infra.sh start / infra.sh stop"
}

# ── Main ──

ACTION=$1
shift 2>/dev/null || true

case "$ACTION" in
    start)  do_start "$@" ;;
    stop)   do_stop "$@" ;;
    -h|--help|help|"") show_help ;;
    *)      log_error "Unknown action: $ACTION"; show_help; exit 1 ;;
esac
