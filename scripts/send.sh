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
    if [[ "$SESSION_NAME" =~ ^agent-([0-9]+(-[0-9]+)?)$ ]]; then
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
CORRELATION_ID="${CORRELATION_ID:-$(cat /proc/sys/kernel/random/uuid)}"
TASK_ID="${TASK_ID:-}"
CYCLE="${CYCLE:-}"

# Compatibilité des prompts existants : extraire l'identité métier des formats
# "start — task-id cycle N", "evaluate — ...", "artifact-required — ...".
# Les variables explicites restent toujours prioritaires.
if [ -z "$CYCLE" ] && [[ "$MESSAGE" =~ [Cc][Yy][Cc][Ll][Ee][[:space:]]+([0-9]+) ]]; then
    CYCLE="${BASH_REMATCH[1]}"
fi
if [ -z "$TASK_ID" ] && [[ "$MESSAGE" =~ ^[^[:space:]]+[[:space:]]+[—-][[:space:]]+([^[:space:]]+) ]]; then
    TASK_ID="${BASH_REMATCH[1]}"
fi

# ── Triangle auto-resolve (règle partagée : resolve_triangle_target, lib.sh) ──
TO_AGENT=$(resolve_triangle_target "$FROM_AGENT" "$TO_AGENT" "send.sh")

# Envoyer via Redis Streams (nouveau format)
MSG_ID=$($REDIS_CLI XADD "$(agent_inbox_key "$TO_AGENT")" MAXLEN '~' "${IO_STREAM_MAXLEN:-10000}" '*' \
    prompt "$MESSAGE" \
    from_agent "$FROM_AGENT" \
    correlation_id "$CORRELATION_ID" \
    task_id "$TASK_ID" \
    cycle "$CYCLE" \
    timestamp "$TIMESTAMP" 2>/dev/null)

if [ -z "$MSG_ID" ]; then
    echo "ko: XADD failed for agent $TO_AGENT (REDIS_CLI=$REDIS_CLI)" >&2
    exit 1
fi

if ! tmux has-session -t "=$(agent_session_name "$TO_AGENT")" 2>/dev/null; then
    echo "ko: agent $TO_AGENT not running — msg $MSG_ID in orphan queue" >&2
    exit 1
fi

echo "ok: $TO_AGENT $MSG_ID corr=$CORRELATION_ID"
