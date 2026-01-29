#!/bin/bash
# start-bridge-agents.sh - Lance des agents avec le nouveau bridge PTY
# Usage: ./start-bridge-agents.sh 300           # Lance agent 300 (interactif)
#        ./start-bridge-agents.sh 300 310       # Lance agents 300-309 (headless tmux)
#        ./start-bridge-agents.sh all           # Lance tous les agents configurés

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/../.."
AGENT_SCRIPT="$BASE_DIR/core/agent-bridge/agent.py"
LOG_DIR="$BASE_DIR/logs"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Agents configuration
# Option 1: Use agents.conf if exists
# Option 2: Auto-detect from prompts/ directory
# Option 3: Fallback to defaults

PROMPTS_DIR="$BASE_DIR/prompts"
AGENTS_CONF="$BASE_DIR/agents.conf"

load_agents() {
    AGENTS=()

    # Option 1: Read from agents.conf if exists
    if [ -f "$AGENTS_CONF" ]; then
        while IFS=: read -r id desc || [ -n "$id" ]; do
            [[ "$id" =~ ^#.*$ ]] && continue  # Skip comments
            [[ -z "$id" ]] && continue         # Skip empty lines
            AGENTS+=("$id:$desc")
        done < "$AGENTS_CONF"
        log_info "Loaded ${#AGENTS[@]} agents from agents.conf"
        return
    fi

    # Option 2: Auto-detect from prompts/ directory
    if [ -d "$PROMPTS_DIR" ]; then
        for prompt_file in "$PROMPTS_DIR"/[0-9][0-9][0-9]-*.md; do
            [ -f "$prompt_file" ] || continue
            filename=$(basename "$prompt_file" .md)
            id="${filename%%-*}"
            desc="${filename#*-}"
            AGENTS+=("$id:$desc")
        done
        if [ ${#AGENTS[@]} -gt 0 ]; then
            log_info "Auto-detected ${#AGENTS[@]} agents from prompts/"
            return
        fi
    fi

    # Option 3: Fallback defaults
    AGENTS=(
        "000:Super-Master"
        "100:Master"
        "200:Explorer"
        "300:Developer"
        "400:Merge"
        "500:Test"
        "600:Release"
    )
    log_warn "Using default agents (no agents.conf or prompts found)"
}

load_agents

mkdir -p "$LOG_DIR"

# Claude configuration - needed for API authentication
# Set these environment variables or adjust the defaults below
# Option 1: Set CLAUDE_CONFIG_DIR to your Claude config directory
# Option 2: Use default ~/.claude (standard Claude Code installation)
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CLAUDE_PROFILES_DIR="${CLAUDE_PROFILES_DIR:-}"

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
    SESSION_NAME="agent-$agent_id"

    # Check if session exists
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_warn "Session $SESSION_NAME already exists, skipping"
        return
    fi

    log_info "Starting agent $agent_id in tmux..."

    mkdir -p "$LOG_DIR/$agent_id"

    # Start in tmux INTERACTIVE (no --headless)
    # PYTHONUNBUFFERED=1 forces real-time output through tee
    tmux new-session -d -s "$SESSION_NAME" \
        "export CLAUDE_CONFIG_DIR='$CLAUDE_CONFIG_DIR'; \
         export CLAUDE_PROFILES_DIR='$CLAUDE_PROFILES_DIR'; \
         export PYTHONUNBUFFERED=1; \
         python3 '$AGENT_SCRIPT' $agent_id 2>&1 | tee -a '$LOG_DIR/$agent_id/bridge.log'; \
         echo 'Agent stopped. Press Enter to close.'; read"

    log_ok "Agent $agent_id started in tmux: $SESSION_NAME"
}

start_range() {
    local start_id=$1
    local end_id=$2

    log_info "Starting agents $start_id to $((end_id - 1))..."
    echo ""

    for ((i=start_id; i<end_id; i++)); do
        start_single_agent "$i"
    done
}

start_all() {
    log_info "Starting all configured agents..."
    echo ""

    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id desc <<< "$agent"
        start_single_agent "$id"
    done
}

show_help() {
    echo "Usage: $0 <agent_id|all>"
    echo ""
    echo "Examples:"
    echo "  $0 300           # Start agent 300"
    echo "  $0 all           # Start all configured agents"
    echo ""
    echo "Configured agents (${#AGENTS[@]}):"
    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id desc <<< "$agent"
        echo "  $id - $desc"
    done
}

# Main
ensure_redis

case "$1" in
    "")
        show_help
        exit 1
        ;;
    "all")
        start_all
        ;;
    *)
        start_single_agent "$1"
        ;;
esac
