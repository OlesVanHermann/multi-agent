#!/bin/bash
# bridge.sh — Restart bridge processes (window :bridge) without killing Claude
#
# Usage:
#   ./scripts/bridge.sh restart all        Restart all bridges
#   ./scripts/bridge.sh restart 345        Restart bridge for 345 (+ x45 satellites)
#   ./scripts/bridge.sh restart 345-945    Restart bridge for specific satellite

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BRIDGE_SCRIPT="$BASE_DIR/core/agent-bridge/agent.py"
LOG_DIR="$BASE_DIR/logs"
PROMPTS_DIR="$BASE_DIR/prompts"

# Auto-detect MA_PREFIX
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Resolve x45 directory
find_x45_dir() {
    local id="$1"
    [ -d "$PROMPTS_DIR/$id" ] && echo "$PROMPTS_DIR/$id" && return 0
    for d in "$PROMPTS_DIR"/${id}-*/; do
        [ -d "$d" ] && echo "${d%/}" && return 0
    done
    return 1
}

# Get all agent IDs for an x45 triangle
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

restart_bridge() {
    local agent_id="$1"
    local SESSION="${MA_PREFIX}-agent-$agent_id"

    if ! tmux has-session -t "$SESSION" 2>/dev/null; then
        log_warn "$SESSION not found, skip"
        return
    fi

    # Check if bridge window exists
    if ! tmux list-windows -t "$SESSION" 2>/dev/null | grep -q "bridge"; then
        log_warn "$SESSION has no bridge window, skip"
        return
    fi

    # Kill current bridge process (send C-c then wait)
    tmux send-keys -t "$SESSION:bridge" C-c 2>/dev/null
    sleep 1

    # Restart bridge with new code
    mkdir -p "$LOG_DIR/$agent_id"
    tmux send-keys -t "$SESSION:bridge" \
        "cd '$BASE_DIR' && MA_PREFIX=$MA_PREFIX python3 '$BRIDGE_SCRIPT' $agent_id 2>&1 | tee -a '$LOG_DIR/$agent_id/bridge.log'" Enter

    log_ok "$agent_id bridge restarted"
}

restart_all() {
    log_info "Restarting all bridges..."
    local count=0
    tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | cut -d: -f1 | while read session; do
        local agent_id="${session#${MA_PREFIX}-agent-}"
        restart_bridge "$agent_id"
        count=$((count + 1))
    done
    log_ok "All bridges restarted"
}

do_restart() {
    local target="${1:?Usage: $0 restart <agent_id|all>}"

    if [ "$target" = "all" ]; then
        restart_all
    else
        # Check if x45 triangle → expand
        local base="${target%%-*}"
        local tri_ids
        tri_ids=$(get_triangle_ids "$base" 2>/dev/null)
        if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ] && [ "$target" = "$base" ]; then
            log_info "x45 triangle $base: $tri_ids"
            for tid in $tri_ids; do
                restart_bridge "$tid"
            done
        else
            restart_bridge "$target"
        fi
    fi
}

show_help() {
    echo "Usage: $0 restart <agent_id|all>"
    echo ""
    echo "  $0 restart all       Restart all bridges"
    echo "  $0 restart 345       Restart bridge for 345 (+ x45 satellites)"
    echo "  $0 restart 345-945   Restart specific bridge"
}

ACTION="${1:-}"
shift 2>/dev/null || true

case "$ACTION" in
    r|restart) do_restart "$@" ;;
    -h|--help|help|"") show_help ;;
    *) log_err "Unknown: $ACTION"; show_help; exit 1 ;;
esac
