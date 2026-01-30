#!/bin/bash
# stop-bridge-agents.sh - Arrête les agents bridge
# Usage: ./stop-bridge-agents.sh           # Arrête tous les agents
#        ./stop-bridge-agents.sh 300 310   # Arrête agents 300-309

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'

log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_info() { echo -e "[INFO] $1"; }

if [ $# -eq 0 ]; then
    log_info "Stopping all agent-* tmux sessions (except 9XX Architects)..."
    tmux ls 2>/dev/null | grep "^agent-" | cut -d: -f1 | while read session; do
        # Extract agent ID from session name (agent-300 -> 300)
        agent_id="${session#agent-}"
        # Skip 9XX agents (Architects)
        if [[ "$agent_id" =~ ^9[0-9][0-9]$ ]]; then
            echo "  - Skipping $session (Architect)"
            continue
        fi
        tmux kill-session -t "$session" 2>/dev/null && log_ok "Killed $session"
    done
else
    START_ID=$1
    END_ID=${2:-$((START_ID + 1))}

    log_info "Stopping agents $START_ID to $((END_ID - 1))..."
    for ((i=START_ID; i<END_ID; i++)); do
        SESSION_NAME="agent-$i"
        if tmux kill-session -t "$SESSION_NAME" 2>/dev/null; then
            log_ok "Killed $SESSION_NAME"
        else
            echo "  - $SESSION_NAME not running"
        fi
    done
fi

# Update Redis status
log_info "Updating Redis status..."
for key in $(redis-cli KEYS "ma:agent:*" 2>/dev/null | grep -E "^ma:agent:[0-9]+$"); do
    agent_id=$(echo "$key" | cut -d: -f3)
    redis-cli HSET "$key" status "stopped" > /dev/null 2>&1
done

log_ok "Done"
