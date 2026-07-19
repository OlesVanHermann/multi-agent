#!/bin/bash
# done.sh - Émet un signal de complétion DONE/SCORE via le canal Redis dédié (A7)
# Usage: ./done.sh <to_agent> DONE [détails...]
#        ./done.sh <to_agent> SCORE <n> [détails...]
#
# Le signal est :
#   1. journalisé dans le stream completion (audit)
#   2. délivré dans l'inbox de l'agent cible (format FROM:{id}|{signal})
#
# Canal EXPLICITE : seul ce script (exécuté par l'agent) émet un signal.
# Le bridge ne scanne plus le texte des réponses (anti faux DONE).
#
# Auto-détecte l'émetteur depuis le nom de session tmux (agent-NNN -> NNN)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
source "$SCRIPT_DIR/redis.sh"
source "$SCRIPT_DIR/lib.sh"

TO_AGENT=$1
SIGNAL_TYPE=$2
shift 2 2>/dev/null || true

usage() {
    echo "Usage: $0 <to_agent> DONE [détails...]" >&2
    echo "       $0 <to_agent> SCORE <n> [détails...]" >&2
    exit 1
}

[ -z "$TO_AGENT" ] || [ -z "$SIGNAL_TYPE" ] && usage

if ! is_valid_agent_id "$TO_AGENT"; then
    echo "Error: Invalid agent ID format: $TO_AGENT (expected NNN or NNN-NNN)" >&2
    exit 1
fi

# Validate signal
case "$SIGNAL_TYPE" in
    DONE)
        SIGNAL="DONE"
        VALUE=""
        ;;
    SCORE)
        VALUE=$1
        shift 2>/dev/null || true
        if [[ ! "$VALUE" =~ ^[0-9]+$ ]]; then
            echo "Error: SCORE requires a numeric value: $0 <to> SCORE <n> [détails]" >&2
            exit 1
        fi
        SIGNAL="SCORE $VALUE"
        ;;
    *)
        echo "Error: Unknown signal '$SIGNAL_TYPE' (expected DONE or SCORE)" >&2
        usage
        ;;
esac

DETAILS="$*"
[ -n "$DETAILS" ] && SIGNAL="$SIGNAL $DETAILS"

# Auto-detect from_agent from tmux session name
if [ -n "$TMUX" ]; then
    SESSION_NAME=$(tmux display-message -p '#S' 2>/dev/null || echo "")
    if [[ "$SESSION_NAME" =~ ^agent-([0-9]+(-[0-9]+)?)$ ]]; then
        FROM_AGENT="${BASH_REMATCH[1]}"
    fi
fi
FROM_AGENT=${FROM_AGENT:-cli}

if [ "$FROM_AGENT" = "$TO_AGENT" ]; then
    echo "Error: an agent never sends DONE/SCORE to itself" >&2
    exit 1
fi

# Triangle auto-resolve (règle partagée : resolve_triangle_target, lib.sh)
TO_AGENT=$(resolve_triangle_target "$FROM_AGENT" "$TO_AGENT" "done.sh")

TIMESTAMP=$(date +%s)
CORRELATION_ID="${CORRELATION_ID:-}"
TASK_ID="${TASK_ID:-}"
CYCLE="${CYCLE:-}"

# 1. Audit : stream de complétion dédié
# V3 : origin=agent — sur une tâche à verify_cmd, ce signal est consultatif ;
# seul origin=verify (émis par verifier.py) fait foi.
$REDIS_CLI XADD "completion" MAXLEN '~' "${STREAM_MAXLEN:-1000}" '*' \
    from "$FROM_AGENT" \
    to "$TO_AGENT" \
    signal "$SIGNAL" \
    origin "agent" \
    correlation_id "$CORRELATION_ID" \
    task_id "$TASK_ID" \
    cycle "$CYCLE" \
    timestamp "$TIMESTAMP" >/dev/null 2>&1

# 2. Délivrance : inbox de la cible
MSG_ID=$($REDIS_CLI XADD "$(agent_inbox_key "$TO_AGENT")" MAXLEN '~' "${IO_STREAM_MAXLEN:-10000}" '*' \
    prompt "FROM:${FROM_AGENT}|${SIGNAL}" \
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
    echo "ko: agent $TO_AGENT not running — signal $MSG_ID in orphan queue" >&2
    exit 1
fi

echo "ok: $TO_AGENT $MSG_ID"
