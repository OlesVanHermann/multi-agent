#!/bin/bash
# done.sh - Émet un terminal métier corrélé via le canal Redis dédié (A7)
# Usage: ./done.sh <to_agent> DONE [détails...]
#        ./done.sh <to_agent> SCORE <n> [détails...]
#
# Le signal est :
#   1. journalisé dans le stream completion (audit)
#   2. délivré dans l'inbox de l'agent cible (identité dans l'enveloppe Redis)
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
    echo "       $0 <to_agent> BLOCKED|INFO_REQUIRED|ERROR|ARTIFACT_READY|PROTOCOL_ERROR|ARBITRAGE|CONCLUSION|PROMPT_RELOADED [détails...]" >&2
    exit 1
}

[ -z "$TO_AGENT" ] || [ -z "$SIGNAL_TYPE" ] && usage

if ! is_valid_agent_id "$TO_AGENT"; then
    echo "Error: Invalid agent ID format: $TO_AGENT (expected NNN or NNN-NNN)" >&2
    exit 1
fi

# Validate signal
case "$SIGNAL_TYPE" in
    DONE|BLOCKED|INFO_REQUIRED|ERROR|ARTIFACT_READY|PROTOCOL_ERROR|ARBITRAGE|CONCLUSION|PROMPT_RELOADED)
        SIGNAL="$SIGNAL_TYPE"
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
        echo "Error: Unknown terminal '$SIGNAL_TYPE'" >&2
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
REQUESTER_ID="${REQUESTER_ID:-$TO_AGENT}"
OWNER_ID="${OWNER_ID:-$TO_AGENT}"

close_obligation() {
    python3 "$SCRIPT_DIR/agent-bridge/obligations.py" close \
        --base "$BASE_DIR" \
        --task "$TASK_ID" \
        --cycle "$CYCLE" \
        --agent "$FROM_AGENT" \
        --correlation "$CORRELATION_ID" \
        --event "$SIGNAL_TYPE" >/dev/null 2>&1 || \
        echo "warning: durable obligation cleanup failed" >&2
}

if [ "$FROM_AGENT" != "cli" ]; then
    if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "unknown" ] \
       || [ -z "$CYCLE" ] || [ "$CYCLE" = "unknown" ] \
       || [ -z "$CORRELATION_ID" ]; then
        case "$SIGNAL_TYPE" in
            INFO_REQUIRED|PROTOCOL_ERROR)
                if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "unknown" ]; then
                    TASK_ID="unattributed"
                fi
                if [ -z "$CYCLE" ] || [ "$CYCLE" = "unknown" ]; then
                    CYCLE="unattributed"
                fi
                CORRELATION_ID="${CORRELATION_ID:-rescue-$(cat /proc/sys/kernel/random/uuid)}"
                echo "rescue: incomplete metadata, emitting $SIGNAL_TYPE under corr=$CORRELATION_ID" >&2
                ;;
            *)
                echo "invalid: terminal requires TASK_ID, CYCLE and CORRELATION_ID" >&2
                echo "hint: emit INFO_REQUIRED or PROTOCOL_ERROR to report the missing metadata" >&2
                exit 2
                ;;
        esac
    fi
fi

# La clé réserve la combinaison terminale ; sa valeur identifie le contenu.
# Un rejeu strict du même contenu est idempotent. Un contenu différent n'est
# jamais assimilé à une livraison réussie.
DEDUP_KEY="terminal:${FROM_AGENT}:${SIGNAL_TYPE}:${TASK_ID}:${CYCLE}:${CORRELATION_ID}"
SIGNAL_FINGERPRINT=$(printf '%s' "$SIGNAL" | sha256sum | cut -d' ' -f1)
DEDUP_RESULT=$($REDIS_CLI SET "$DEDUP_KEY" "$SIGNAL_FINGERPRINT" NX EX "${TERMINAL_DEDUP_TTL:-604800}" 2>/dev/null)
if [ "$DEDUP_RESULT" != "OK" ]; then
    PREVIOUS=$($REDIS_CLI GET "$DEDUP_KEY" 2>/dev/null)
    if [ "$PREVIOUS" = "$SIGNAL_FINGERPRINT" ]; then
        close_obligation
        echo "replay: $TO_AGENT event=$SIGNAL_TYPE task=$TASK_ID cycle=$CYCLE corr=$CORRELATION_ID state=ALREADY_DELIVERED"
        exit 0
    fi
    echo "refused: $TO_AGENT event=$SIGNAL_TYPE task=$TASK_ID cycle=$CYCLE corr=$CORRELATION_ID state=NOT_DELIVERED" >&2
    echo "remedy: this terminal slot is already consumed by a different payload; open a new CYCLE/CORR then re-emit" >&2
    exit 3
fi

# 1. Audit : stream de complétion dédié
# V3 : origin=agent — sur une tâche à verify_cmd, ce signal est consultatif ;
# seul origin=verify (émis par verifier.py) fait foi.
COMPLETION_ID=$($REDIS_CLI XADD "completion" MAXLEN '~' "${STREAM_MAXLEN:-1000}" '*' \
    from "$FROM_AGENT" \
    to "$TO_AGENT" \
    event "$SIGNAL_TYPE" \
    signal "$SIGNAL" \
    origin "agent" \
    correlation_id "$CORRELATION_ID" \
    task_id "$TASK_ID" \
    cycle "$CYCLE" \
    requester "$REQUESTER_ID" \
    owner "$OWNER_ID" \
    timestamp "$TIMESTAMP" 2>/dev/null)

if [ -z "$COMPLETION_ID" ]; then
    $REDIS_CLI DEL "$DEDUP_KEY" >/dev/null 2>&1
    echo "invalid: completion XADD failed for agent $TO_AGENT" >&2
    exit 1
fi

# Le stream completion fait foi même si la cible est momentanément absente.
# Archiver l'obligation après ce XADD réussi, jamais avant.
close_obligation

# 2. Délivrance : inbox de la cible
MSG_ID=$($REDIS_CLI XADD "$(agent_inbox_key "$TO_AGENT")" MAXLEN '~' "${IO_STREAM_MAXLEN:-10000}" '*' \
    prompt "EVENT:${SIGNAL_TYPE}|TASK:${TASK_ID}|CYCLE:${CYCLE}|CORR:${CORRELATION_ID}|DETAIL:${SIGNAL}" \
    from_agent "$FROM_AGENT" \
    event "$SIGNAL_TYPE" \
    correlation_id "$CORRELATION_ID" \
    task_id "$TASK_ID" \
    cycle "$CYCLE" \
    requester "$REQUESTER_ID" \
    owner "$OWNER_ID" \
    timestamp "$TIMESTAMP" 2>/dev/null)

if [ -z "$MSG_ID" ]; then
    $REDIS_CLI DEL "$DEDUP_KEY" >/dev/null 2>&1
    echo "ko: XADD failed for agent $TO_AGENT (REDIS_CLI=$REDIS_CLI)" >&2
    exit 1
fi

if ! tmux has-session -t "=$(agent_session_name "$TO_AGENT")" 2>/dev/null; then
    echo "queued: $TO_AGENT $MSG_ID corr=$CORRELATION_ID state=ORPHANED" >&2
    exit 2
fi

echo "ok: $TO_AGENT $MSG_ID corr=$CORRELATION_ID state=DELIVERED"
