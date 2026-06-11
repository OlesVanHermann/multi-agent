#!/bin/bash
# send.sh - Envoie un message à un agent via Redis Streams
# Usage: ./send.sh <to_agent> <message>
#        ./send.sh 300 "go example.com"
#
# Auto-detects sender from tmux session name (agent-100 -> from_agent=100)

# No set -e — handle errors explicitly for reliable error reporting

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
source "$SCRIPT_DIR/redis.sh"
source "$SCRIPT_DIR/lib.sh"
# Auto-detect MA_PREFIX from project-config.md if not set
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-A}"

TO_AGENT=$1
shift 2>/dev/null || true

if [ -z "$TO_AGENT" ]; then
    echo "Usage: $0 <to_agent> <message>"
    echo "       $0 300 'go example.com'"
    exit 1
fi

if ! is_valid_agent_id "$TO_AGENT" && [ "$TO_AGENT" != "all" ]; then
    echo "Error: Invalid agent ID format: $TO_AGENT (expected NNN or NNN-NNN)" >&2
    exit 1
fi

if [[ ! "$MA_PREFIX" =~ ^[A-Za-z0-9]+$ ]]; then
    echo "Error: Invalid MA_PREFIX: $MA_PREFIX" >&2
    exit 1
fi

# Message from args or stdin
if [ $# -gt 0 ]; then
    MESSAGE="$*"
else
    MESSAGE=$(cat)
fi

if [ -z "$MESSAGE" ]; then
    echo "Error: No message provided"
    exit 1
fi

# Auto-detect from_agent from tmux session name
if [ -n "$TMUX" ]; then
    SESSION_NAME=$(tmux display-message -p '#S' 2>/dev/null || echo "")
    if [[ "$SESSION_NAME" =~ ^${MA_PREFIX}-agent-([0-9]+(-[0-9]+)?)$ ]]; then
        FROM_AGENT="${BASH_REMATCH[1]}"
    fi
fi

# Fallback to env var or "cli"
FROM_AGENT=${FROM_AGENT:-cli}

if [ -z "$TO_AGENT" ]; then
    echo "Usage: $0 <from_agent> <to_agent> <message>"
    echo "       $0 100 300 'go example.com'"
    exit 1
fi

if [ -z "$MESSAGE" ]; then
    echo "Error: No message provided"
    exit 1
fi

TIMESTAMP=$(date +%s)

# ── Triangle auto-resolve ──
# If sender is in a triangle (NNN-XXX) and target is a bare suffix (YYY),
# resolve target to NNN-YYY (same triangle as sender).
if [[ "$FROM_AGENT" =~ ^([0-9]+)-[0-9]+$ ]]; then
    TRIANGLE="${BASH_REMATCH[1]}"
    if [[ "$TO_AGENT" =~ ^[0-9]+$ ]] && [[ ! "$TO_AGENT" =~ - ]]; then
        RESOLVED="${TRIANGLE}-${TO_AGENT}"
        echo "[send.sh] WARNING: auto-resolved $TO_AGENT -> $RESOLVED (sender $FROM_AGENT is in triangle $TRIANGLE)" >&2
        TO_AGENT="$RESOLVED"
    fi
fi

# Envoyer via Redis Streams (nouveau format)
MSG_ID=$($REDIS_CLI XADD "${MA_PREFIX}:agent:${TO_AGENT}:inbox" MAXLEN '~' "${IO_STREAM_MAXLEN:-10000}" '*' \
    prompt "$MESSAGE" \
    from_agent "$FROM_AGENT" \
    timestamp "$TIMESTAMP" 2>/dev/null)

if [ -z "$MSG_ID" ]; then
    echo "ko: XADD failed for agent $TO_AGENT (REDIS_CLI=$REDIS_CLI)" >&2
    exit 1
fi

if ! tmux has-session -t "${MA_PREFIX}-agent-${TO_AGENT}" 2>/dev/null; then
    echo "ko: agent $TO_AGENT not running — msg $MSG_ID in orphan queue" >&2
    exit 1
fi

echo "ok: $TO_AGENT $MSG_ID"
