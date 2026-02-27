#!/bin/bash
# agent.sh - Start/stop agents
# Usage: ./scripts/agent.sh start <agent_id|all>
#        ./scripts/agent.sh stop <agent_id|all>

set -e

# Raise open files limit (each agent = tmux session + claude + bridge)
ulimit -n 10240 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
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
    # Protected: only 000 and its satellites (000-500, 000-900, etc.)
    local base="${1%%-*}"  # 345-500 → 345, 000-900 → 000
    [[ "$base" == "000" ]]
}

# Resolve x45 directory (plain or verbose name)
find_x45_dir() {
    local id="$1"
    # Exact match
    [ -d "$PROMPTS_DIR/$id" ] && echo "$PROMPTS_DIR/$id" && return 0
    # Verbose match: 341-analyse-archi-...
    for d in "$PROMPTS_DIR"/${id}-*/; do
        [ -d "$d" ] && echo "${d%/}" && return 0
    done
    return 1
}

# Get all agent IDs for an x45 triangle (main + satellites)
get_triangle_ids() {
    local id="$1"
    local dir
    dir=$(find_x45_dir "$id") || return 1
    local ids=("$id")
    for sat_link in "$dir"/${id}-[0-9][0-9][0-9].md; do
        [ -f "$sat_link" ] || continue
        ids+=("$(basename "$sat_link" .md)")
    done
    echo "${ids[@]}"
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
    tmux send-keys -t "$SESSION_NAME" "cd '$BASE_DIR' && unset CLAUDECODE && claude --dangerously-skip-permissions" Enter
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

wait_claude_ready() {
    # Wait until Claude CLI is ready in a tmux session (shows ❯ prompt)
    local session=$1
    local max_wait=${2:-30}  # max seconds to wait
    local elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        local pane_content
        pane_content=$(tmux capture-pane -t "$session:0" -p 2>/dev/null)
        # Claude is ready when we see the input prompt marker
        if echo "$pane_content" | grep -qE '❯|Try "'; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1  # timeout
}

start_all() {
    log_info "Auto-detecting agents from prompts/..."

    # Collect all agent IDs
    local agents=()

    # Format 1: flat prompts (pipeline standard) — prompts/XXX-*.md
    for prompt_file in "$PROMPTS_DIR"/[0-9][0-9][0-9]-*.md; do
        [ -f "$prompt_file" ] || continue
        local filename=$(basename "$prompt_file" .md)
        local agent_id="${filename%%-*}"
        is_protected "$agent_id" && continue
        # Skip duplicates (e.g. 390-rapport.md + 390-PLAN-MAXIMAL.md)
        [[ " ${agents[*]} " == *" $agent_id "* ]] && continue
        # Skip already running
        local SESSION_NAME="${MA_PREFIX}-agent-$agent_id"
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            log_warn "$SESSION_NAME already exists, skipping"
            continue
        fi
        agents+=("$agent_id")
    done

    # Format 2: x45 directory prompts — prompts/XXX/ or prompts/XXX-name/
    for agent_dir in "$PROMPTS_DIR"/[0-9][0-9][0-9] "$PROMPTS_DIR"/[0-9][0-9][0-9]-*; do
        [ -d "$agent_dir" ] || continue
        local dir_name=$(basename "$agent_dir")
        # Extract numeric prefix (341 from 341-analyse-archi-...)
        local agent_id="${dir_name:0:3}"
        { [ -f "$agent_dir/${agent_id}-system.md" ] || [ -f "$agent_dir/system.md" ]; } || continue
        is_protected "$agent_id" && continue
        # Skip duplicates (already found in flat format or verbose duplicate)
        if ! [[ " ${agents[*]} " == *" $agent_id "* ]]; then
            # Skip already running
            local SESSION_NAME="${MA_PREFIX}-agent-$agent_id"
            if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
                log_warn "$SESSION_NAME already exists, skipping"
            else
                agents+=("$agent_id")
            fi
        fi

        # x45 satellites: find XXX-{suffix}.md symlinks (e.g. 345-500.md, 345-700.md)
        # Always scan satellites even if worker is already running
        for sat_link in "$agent_dir"/${agent_id}-[0-9][0-9][0-9].md; do
            [ -f "$sat_link" ] || continue
            local sat_name=$(basename "$sat_link" .md)  # e.g. 345-500
            is_protected "$sat_name" && continue
            [[ " ${agents[*]} " == *" $sat_name "* ]] && continue
            local SAT_SESSION="${MA_PREFIX}-agent-$sat_name"
            if tmux has-session -t "$SAT_SESSION" 2>/dev/null; then
                log_warn "$SAT_SESSION already exists, skipping"
                continue
            fi
            agents+=("$sat_name")
        done
    done

    local total=${#agents[@]}
    if [ "$total" -eq 0 ]; then
        log_warn "No agents to start"
        return
    fi

    local BATCH_SIZE=10
    local batch_num=0

    for ((i=0; i<total; i+=BATCH_SIZE)); do
        local batch=("${agents[@]:i:BATCH_SIZE}")
        batch_num=$((batch_num + 1))
        log_info "Batch $batch_num: ${batch[*]}"

        # Phase 1: create all tmux sessions + launch claude
        for agent_id in "${batch[@]}"; do
            local SESSION="${MA_PREFIX}-agent-$agent_id"
            mkdir -p "$LOG_DIR/$agent_id"
            tmux new-session -d -s "$SESSION"
            tmux send-keys -t "$SESSION" "cd '$BASE_DIR' && unset CLAUDECODE && claude --dangerously-skip-permissions" Enter
        done

        # Phase 2: wait for Claude to be ready in ALL sessions, then configure
        log_info "  Waiting for Claude to start in ${#batch[@]} sessions..."
        for agent_id in "${batch[@]}"; do
            local SESSION="${MA_PREFIX}-agent-$agent_id"
            if wait_claude_ready "$SESSION" 30; then
                # Read model
                local MODEL=""
                if [ -f "$PROMPTS_DIR/${agent_id}.model" ]; then
                    MODEL=$(cat "$PROMPTS_DIR/${agent_id}.model" | tr -d '[:space:]')
                elif [ -f "$PROMPTS_DIR/default.model" ]; then
                    MODEL=$(cat "$PROMPTS_DIR/default.model" | tr -d '[:space:]')
                fi

                # Send /model if needed
                if [ -n "$MODEL" ]; then
                    tmux send-keys -t "$SESSION" "/model $MODEL" Enter
                    sleep 1
                    tmux send-keys -t "$SESSION" Enter
                    sleep 1
                fi

                # Start bridge in second window
                tmux new-window -t "$SESSION" -n bridge
                tmux send-keys -t "$SESSION:bridge" "cd '$BASE_DIR' && sleep 3 && MA_PREFIX=$MA_PREFIX python3 '$BRIDGE_SCRIPT' $agent_id 2>&1 | tee -a '$LOG_DIR/$agent_id/bridge.log'" Enter
                tmux select-window -t "$SESSION:0"

                log_ok "  Agent $agent_id ready"
            else
                log_error "  Agent $agent_id: Claude did not start within 30s"
            fi
        done

        log_ok "Batch $batch_num done: ${#batch[@]} agents"
    done

    echo ""
    log_ok "Started $total agents ($batch_num batches of max $BATCH_SIZE)"
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
    if ! lsof -iTCP:8090 -sTCP:LISTEN &>/dev/null 2>&1; then
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
            # x45 triangle? expand to all satellites
            local tri_ids
            tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null)
            if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
                log_info "x45 triangle $agent_id: $tri_ids"
                for tid in $tri_ids; do
                    start_single "$tid"
                done
            else
                start_single "$agent_id"
            fi
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
    log_info "Stopping agents (000 is NEVER stopped)..."
    tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | cut -d: -f1 | while read session; do
        local agent_id="${session#${MA_PREFIX}-agent-}"
        if is_protected "$agent_id"; then
            log_warn "Skipping $session (protected)"
            continue
        fi
        tmux kill-session -t "$session" 2>/dev/null && log_ok "Killed $session"
    done

    # Update Redis status
    for key in $(redis-cli KEYS "${MA_PREFIX}:agent:*" 2>/dev/null | grep -E "^${MA_PREFIX}:agent:[0-9]+(-[0-9]+)?$"); do
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
            # x45 triangle? expand to all satellites
            local tri_ids
            tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null)
            if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
                log_info "x45 triangle $agent_id: $tri_ids"
                for tid in $tri_ids; do
                    stop_single "$tid"
                done
            else
                stop_single "$agent_id"
            fi
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
    echo "  $0 stop all        Stop all (except 000)"
    echo ""
    echo "  000 is protected — use infra.sh start / infra.sh stop"
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
