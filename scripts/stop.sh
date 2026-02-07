#!/bin/bash
# stop-agents.sh - Stop all agent tmux sessions
# Usage: ./stop-agents.sh           # Stop all (except 9XX)
#        ./stop-agents.sh all       # Stop ALL including 9XX
#        ./stop-agents.sh 300       # Stop specific agent

set -e

MA_PREFIX="${MA_PREFIX:-ma}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_info() { echo -e "[INFO] $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

case "$1" in
    "all"|"")
        log_info "Stopping agent sessions (9XX Architects are NEVER stopped)..."
        ;;
    *)
        # Stop specific agent
        SESSION="${MA_PREFIX}-agent-$1"
        if tmux kill-session -t "$SESSION" 2>/dev/null; then
            log_ok "Killed $SESSION"
        else
            echo "Session $SESSION not found"
        fi
        exit 0
        ;;
esac

# Stop sessions
tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | cut -d: -f1 | while read session; do
    agent_id="${session#${MA_PREFIX}-agent-}"

    # NEVER kill 9XX Architects
    if [[ "$agent_id" =~ ^9[0-9][0-9]$ ]]; then
        log_warn "Skipping $session (Architect - NEVER killed)"
        continue
    fi

    tmux kill-session -t "$session" 2>/dev/null && log_ok "Killed $session"
done

# Update Redis status
log_info "Updating Redis status..."
for key in $(redis-cli KEYS "${MA_PREFIX}:agent:*" 2>/dev/null | grep -E "^${MA_PREFIX}:agent:[0-9]+$"); do
    redis-cli HSET "$key" status "stopped" > /dev/null 2>&1
done

log_ok "Done"
