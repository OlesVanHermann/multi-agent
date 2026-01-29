#!/bin/bash
# tmux.sh - Attach to an agent's tmux session
# Usage: ./scripts/tmux.sh <agent_id>
#        ./scripts/tmux.sh 300

AGENT_ID=${1:-300}
SESSION="agent-${AGENT_ID}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux attach -t "$SESSION"
else
    echo "Session $SESSION not found"
    echo "Available sessions:"
    tmux ls 2>/dev/null | grep agent || echo "  (none)"
fi
