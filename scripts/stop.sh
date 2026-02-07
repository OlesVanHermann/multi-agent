#!/bin/bash
# stop.sh - Stop all agent tmux sessions
# Usage: ./scripts/stop.sh           # Stop all (except 9XX)
#        ./scripts/stop.sh all       # Stop ALL including 9XX
#        ./scripts/stop.sh 300       # Stop specific agent

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
# Auto-detect MA_PREFIX from project-config.md if not set
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"

log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_info() { echo -e "[INFO] $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

case "$1" in
    "all"|"")
        log_info "Stopping agent sessions (000 Architect and 9XX are NEVER stopped)..."
        ;;
    *)
        # Stop specific agent (but protect 000 and 9XX)
        if [[ "$1" =~ ^(9[0-9][0-9]|000)$ ]]; then
            log_warn "Cannot stop agent $1 via stop.sh. Use ./scripts/stop-000.sh for Architect."
            exit 1
        fi
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

    # NEVER kill 000 (Architect) or 9XX
    if [[ "$agent_id" =~ ^(9[0-9][0-9]|000)$ ]]; then
        log_warn "Skipping $session (Architect - NEVER killed, use stop-000.sh)"
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
