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
PROVIDED_CORRELATION_ID="${CORRELATION_ID:-}"
TASK_ID="${TASK_ID:-}"
CYCLE="${CYCLE:-}"
MESSAGE_EVENT="${MESSAGE_EVENT:-MESSAGE}"
REQUESTER_ID="${REQUESTER_ID:-$FROM_AGENT}"
OWNER_ID="${OWNER_ID:-$FROM_AGENT}"
EXPECTED_EVENT="${EXPECTED_EVENT:-}"

# Une commande opérateur peut rester libre. Entre agents, l'enveloppe est
# obligatoire et le texte ne sert jamais à inventer une métadonnée.
if [ "$FROM_AGENT" != "cli" ]; then
    if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "unknown" ] \
       || [ -z "$CYCLE" ] || [ "$CYCLE" = "unknown" ] \
       || [ -z "$PROVIDED_CORRELATION_ID" ]; then
        echo "invalid: inter-agent message requires TASK_ID, CYCLE and CORRELATION_ID" >&2
        exit 2
    fi
    if [ "$MESSAGE_EVENT" = "DISPATCH" ] && [ -z "$EXPECTED_EVENT" ]; then
        echo "invalid: DISPATCH requires EXPECTED_EVENT" >&2
        exit 2
    fi
fi

# Seul l'opérateur peut obtenir automatiquement une nouvelle corrélation.
# Un agent doit créer ou hériter explicitement de la sienne avant l'appel.
CORRELATION_ID="${PROVIDED_CORRELATION_ID:-$(cat /proc/sys/kernel/random/uuid)}"

# ── Triangle auto-resolve (règle partagée : resolve_triangle_target, lib.sh) ──
TO_AGENT=$(resolve_triangle_target "$FROM_AGENT" "$TO_AGENT" "send.sh")

# Envoyer via Redis Streams (nouveau format)
MSG_ID=$($REDIS_CLI XADD "$(agent_inbox_key "$TO_AGENT")" MAXLEN '~' "${IO_STREAM_MAXLEN:-10000}" '*' \
    prompt "$MESSAGE" \
    from_agent "$FROM_AGENT" \
    event "$MESSAGE_EVENT" \
    correlation_id "$CORRELATION_ID" \
    task_id "$TASK_ID" \
    cycle "$CYCLE" \
    requester "$REQUESTER_ID" \
    owner "$OWNER_ID" \
    expected_event "$EXPECTED_EVENT" \
    timestamp "$TIMESTAMP" 2>/dev/null)

if [ -z "$MSG_ID" ]; then
    echo "ko: XADD failed for agent $TO_AGENT (REDIS_CLI=$REDIS_CLI)" >&2
    exit 1
fi

if ! tmux has-session -t "=$(agent_session_name "$TO_AGENT")" 2>/dev/null; then
    echo "queued: $TO_AGENT $MSG_ID corr=$CORRELATION_ID state=ORPHANED" >&2
    exit 2
fi

echo "ok: $TO_AGENT $MSG_ID corr=$CORRELATION_ID state=DELIVERED"
