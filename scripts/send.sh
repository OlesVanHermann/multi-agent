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

# `=NNN` = adressage global explicite (jamais résolu vers le triangle).
if ! is_valid_agent_id "${TO_AGENT#=}" && [ "$TO_AGENT" != "all" ]; then
    echo "Error: Invalid agent ID format: $TO_AGENT (expected NNN, NNN-NNN, =NNN ou all)" >&2
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

MESSAGE_EVENT="${MESSAGE_EVENT:-MESSAGE}"
EXPECTED_EVENT="${EXPECTED_EVENT:-}"
BUS_PROTOCOL="$SCRIPT_DIR/agent-bridge/bus_protocol.py"

# La cible unicast doit etre canonique avant de calculer event_id. Le broadcast
# garde `all` ici puis derive un event_id distinct pour chaque destinataire.
if [ "$TO_AGENT" != "all" ]; then
    TO_AGENT=$(resolve_triangle_target "$FROM_AGENT" "$TO_AGENT" "send.sh")
fi

CONTEXT_OUTPUT=$(python3 "$BUS_PROTOCOL" context \
    --kind message \
    --from-agent "$FROM_AGENT" \
    --to-agent "$TO_AGENT" \
    --event "$MESSAGE_EVENT" \
    --source-turn-id "${TURN_ID:-}" \
    --task-id "${TASK_ID:-}" \
    --cycle "${CYCLE:-}" \
    --correlation-id "${CORRELATION_ID:-}" \
    --requester "${REQUESTER_ID:-}" \
    --owner "${OWNER_ID:-}" \
    --origin="${TURN_ORIGIN:-${CURRENT_TURN_ORIGIN:-}}" \
    --expected-event "$EXPECTED_EVENT")
CONTEXT_RC=$?
if [ "$CONTEXT_RC" -ne 0 ]; then
    exit "$CONTEXT_RC"
fi
IFS='|' read -r CONTEXT_KIND TURN_ID TASK_ID CYCLE CORRELATION_ID \
    REQUESTER_ID OWNER_ID TURN_ORIGIN <<< "$CONTEXT_OUTPUT"
[ "$CONTEXT_KIND" = "CONTEXT" ] || {
    echo "publish-error: invalid context response" >&2
    exit 1
}

publish_message() {
    local target="$1" owner="$2"
    python3 "$BUS_PROTOCOL" message \
        --from-agent "$FROM_AGENT" \
        --to-agent "$target" \
        --event "$MESSAGE_EVENT" \
        --source-turn-id "$TURN_ID" \
        --task-id "$TASK_ID" \
        --cycle "$CYCLE" \
        --correlation-id "$CORRELATION_ID" \
        --requester "$REQUESTER_ID" \
        --owner "$owner" \
        --origin="$TURN_ORIGIN" \
        --expected-event="$EXPECTED_EVENT" \
        --prompt="$MESSAGE" \
        --maxlen "${IO_STREAM_MAXLEN:-10000}" \
        --ttl "${TERMINAL_DEDUP_TTL:-604800}"
}

# ── Broadcast : fan-out réel sur les sessions vivantes ──
# `agent:all:inbox` n'a AUCUN consommateur : y écrire perdait le message en
# annonçant « queued/ORPHANED ». Le seul broadcast qui existe est un fan-out
# par agent — on le fait ici, en échouant franchement s'il n'y a personne.
if [ "$TO_AGENT" = "all" ]; then
    SENT=0
    while IFS= read -r target; do
        [ "$target" = "$FROM_AGENT" ] && continue
        PUBLISH_OUTPUT=$(publish_message "$target" "$target")
        PUBLISH_RC=$?
        IFS='|' read -r PUBLISH_STATE MSG_ID EVENT_ID DELIVERY_STATE \
            DECISION_ID <<< "$PUBLISH_OUTPUT"
        if [ "$PUBLISH_RC" -eq 0 ]; then
            SENT=$((SENT + 1))
            echo "ok: $target ${MSG_ID:-no-new-stream-entry} event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=$DELIVERY_STATE publish=$PUBLISH_STATE"
        else
            echo "ko: atomic publish failed for agent $target" >&2
        fi
    done < <(list_live_agent_ids)
    if [ "$SENT" -eq 0 ]; then
        echo "invalid: broadcast sans destinataire (aucune session agent vivante)" >&2
        exit 2
    fi
    echo "broadcast: $SENT agent(s) corr=$CORRELATION_ID"
    exit 0
fi

PUBLISH_OUTPUT=$(publish_message "$TO_AGENT" "$OWNER_ID")
PUBLISH_RC=$?
IFS='|' read -r PUBLISH_STATE MSG_ID EVENT_ID DELIVERY_STATE \
    DECISION_ID <<< "$PUBLISH_OUTPUT"
if [ "$PUBLISH_RC" -ne 0 ]; then
    [ "$PUBLISH_RC" -eq 3 ] && \
        echo "refused: $TO_AGENT event=$MESSAGE_EVENT turn=$TURN_ID state=NOT_DELIVERED" >&2
    exit "$PUBLISH_RC"
fi

if [ "$PUBLISH_STATE" = "REPLAY" ]; then
    echo "replay: $TO_AGENT ${MSG_ID:-no-new-stream-entry} event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=$DELIVERY_STATE"
    exit 0
fi
[ "$PUBLISH_STATE" = "CREATED" ] || {
    echo "publish-error: invalid message result '$PUBLISH_STATE'" >&2
    exit 1
}

if [ "$DELIVERY_STATE" = "SUPPRESSED_BY_DECISION" ]; then
    echo "ok: $TO_AGENT no-new-stream-entry event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=SUPPRESSED_BY_DECISION"
    exit 0
fi
if [ "$DELIVERY_STATE" != "DELIVERED" ] || [ -z "$MSG_ID" ]; then
    echo "publish-error: message result is inconsistent" >&2
    exit 1
fi

if ! tmux has-session -t "=$(agent_session_name "$TO_AGENT")" 2>/dev/null; then
    echo "queued: $TO_AGENT $MSG_ID event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=ORPHANED" >&2
    exit 2
fi

echo "ok: $TO_AGENT $MSG_ID event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=DELIVERED"
