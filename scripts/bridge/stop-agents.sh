#!/bin/bash
# stop-agents.sh - Stop all agent tmux sessions
# Usage: ./stop-agents.sh           # Stop all (except 9XX)
#        ./stop-agents.sh all       # Stop ALL including 9XX
#        ./stop-agents.sh 300       # Stop specific agent

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_info() { echo -e "[INFO] $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

INCLUDE_ARCHITECTS=false

case "$1" in
    "all")
        INCLUDE_ARCHITECTS=true
        log_info "Stopping ALL agent sessions (including 9XX Architects)..."
        ;;
    "")
        log_info "Stopping agent sessions (preserving 9XX Architects)..."
        ;;
    *)
        # Stop specific agent
        SESSION="agent-$1"
        if tmux kill-session -t "$SESSION" 2>/dev/null; then
            log_ok "Killed $SESSION"
        else
            echo "Session $SESSION not found"
        fi
        exit 0
        ;;
esac

# Stop sessions
tmux ls 2>/dev/null | grep "^agent-" | cut -d: -f1 | while read session; do
    agent_id="${session#agent-}"

    # Skip 9XX unless --all
    if [[ "$agent_id" =~ ^9[0-9][0-9]$ ]] && [ "$INCLUDE_ARCHITECTS" = false ]; then
        log_warn "Skipping $session (Architect)"
        continue
    fi

    tmux kill-session -t "$session" 2>/dev/null && log_ok "Killed $session"
done

# Update Redis status
log_info "Updating Redis status..."
for key in $(redis-cli KEYS "ma:agent:*" 2>/dev/null | grep -E "^ma:agent:[0-9]+$"); do
    redis-cli HSET "$key" status "stopped" > /dev/null 2>&1
done

log_ok "Done"
