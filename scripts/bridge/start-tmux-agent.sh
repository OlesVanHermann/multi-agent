#!/bin/bash
# start-tmux-agent.sh - Start agent with interactive Claude + tmux bridge
# Usage: ./start-tmux-agent.sh <agent_id>
#
# This creates TWO tmux panes:
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

AGENT_ID=${1:-300}
SESSION_NAME="agent-$AGENT_ID"

# Check if session exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    log_warn "Session $SESSION_NAME already exists"
    echo "  Attach with: tmux attach -t $SESSION_NAME"
    echo "  Or kill with: tmux kill-session -t $SESSION_NAME"
    exit 1
fi

# Ensure Redis is running
if ! redis-cli ping &>/dev/null; then
    log_error "Redis not running. Start it first."
    exit 1
fi

# Find prompt file
PROMPT_FILE=$(ls "$PROMPTS_DIR"/${AGENT_ID}-*.md 2>/dev/null | head -1)
if [ -z "$PROMPT_FILE" ]; then
    log_warn "No prompt file found for agent $AGENT_ID"
fi

mkdir -p "$LOG_DIR/$AGENT_ID"

log_info "Starting agent $AGENT_ID with interactive Claude..."

# Create tmux session with Claude in main pane
tmux new-session -d -s "$SESSION_NAME" -x 200 -y 50

# Pane 0: Claude interactive
tmux send-keys -t "$SESSION_NAME" "cd '$BASE_DIR' && claude" Enter

# Wait for Claude to start
sleep 2

# Split window horizontally - Pane 1: Bridge process
tmux split-window -t "$SESSION_NAME" -h -p 30

# Pane 1: Bridge (monitors Redis, sends to Claude via tmux)
tmux send-keys -t "$SESSION_NAME.1" "cd '$BASE_DIR' && sleep 3 && python3 '$BRIDGE_SCRIPT' $AGENT_ID 2>&1 | tee -a '$LOG_DIR/$AGENT_ID/bridge.log'" Enter

# Select pane 0 (Claude) as active
tmux select-pane -t "$SESSION_NAME.0"

log_ok "Agent $AGENT_ID started!"
echo ""
echo "  Session: $SESSION_NAME"
echo "  Pane 0 (left):  Claude interactive (MCP enabled)"
echo "  Pane 1 (right): Bridge (Redis monitor)"
echo ""
echo "  Attach: tmux attach -t $SESSION_NAME"
if [ -n "$PROMPT_FILE" ]; then
    echo "  Prompt: lis $PROMPT_FILE"
fi
echo ""
