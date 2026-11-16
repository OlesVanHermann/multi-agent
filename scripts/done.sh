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

# `=NNN` = adressage global explicite (jamais résolu vers le triangle).
if ! is_valid_agent_id "${TO_AGENT#=}"; then
    echo "Error: Invalid agent ID format: $TO_AGENT (expected NNN, NNN-NNN ou =NNN)" >&2
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

# Triangle auto-resolve (règle partagée : resolve_triangle_target, lib.sh)
TO_AGENT=$(resolve_triangle_target "$FROM_AGENT" "$TO_AGENT" "done.sh")

# Anti-auto-envoi APRÈS la résolution : depuis 300-301, « done.sh 301 » est
# résolu en 300-301 — un contrôle placé avant la résolution laissait donc
# passer le terminal auto-adressé qu'il prétend interdire.
if [ "$FROM_AGENT" = "$TO_AGENT" ]; then
    echo "Error: an agent never sends DONE/SCORE to itself" >&2
    exit 1
fi

TIMESTAMP=$(date +%s)
BUS_PROTOCOL="$SCRIPT_DIR/agent-bridge/bus_protocol.py"
CONTEXT_OUTPUT=$(python3 "$BUS_PROTOCOL" context \
    --kind terminal \
    --from-agent "$FROM_AGENT" \
    --to-agent "$TO_AGENT" \
    --event "$SIGNAL_TYPE" \
    --source-turn-id "${TURN_ID:-}" \
    --task-id "${TASK_ID:-}" \
    --cycle "${CYCLE:-}" \
    --correlation-id "${CORRELATION_ID:-}" \
    --requester "${REQUESTER_ID:-}" \
    --owner "${OWNER_ID:-}" \
    --origin="${TURN_ORIGIN:-${CURRENT_TURN_ORIGIN:-}}")
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

# État de comptabilité de l'obligation durable, annexé au rapport de livraison.
# Vide = rien à comptabiliser ou obligation close ; UNRECONCILED = échec exposé.
OBLIGATION_STATE=""

close_obligation() {
    local out rc inconsistency_key
    out=$(python3 "$SCRIPT_DIR/agent-bridge/obligations.py" close \
        --base "$BASE_DIR" \
        --task "$TASK_ID" \
        --cycle "$CYCLE" \
        --agent "$FROM_AGENT" \
        --correlation "$CORRELATION_ID" \
        --event "$SIGNAL_TYPE" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        # Échec de comptabilité APRÈS livraison : le terminal est déjà journalisé
        # dans le stream completion (fait foi). On rend l'écart visible SANS
        # réémettre de terminal — l'obligation durable reste OPEN et sera reprise
        # par la réconciliation du watchdog.
        OBLIGATION_STATE=" obligation=UNRECONCILED"
        echo "unreconciled: durable obligation still OPEN after delivery (${out})" >&2
        # Une seule preuve machine, non actionnable. Elle permet au dashboard
        # et au watchdog de distinguer un défaut de comptabilité d'un travail
        # réellement absent sans réveiller un modèle ni réémettre le terminal.
        inconsistency_key="runtime_inconsistency:${FROM_AGENT}:${TASK_ID}:${CYCLE}:${CORRELATION_ID}:${SIGNAL_TYPE}"
        if [ "$($REDIS_CLI SET "$inconsistency_key" 1 NX EX "${TERMINAL_DEDUP_TTL:-604800}" 2>/dev/null)" = "OK" ]; then
            # XADD échoué = clé de dédup relâchée, sinon la preuve serait
            # perdue pour toute la durée du TTL.
            $REDIS_CLI XADD "runtime:inconsistencies" MAXLEN '~' "${STREAM_MAXLEN:-1000}" '*' \
                from_agent "$FROM_AGENT" \
                to_agent "$TO_AGENT" \
                event "RUNTIME_INCONSISTENCY" \
                task_id "$TASK_ID" \
                cycle "$CYCLE" \
                correlation_id "$CORRELATION_ID" \
                terminal_event "$SIGNAL_TYPE" \
                detail "$out" \
                timestamp "$TIMESTAMP" >/dev/null 2>&1 \
                || $REDIS_CLI DEL "$inconsistency_key" >/dev/null 2>&1
        fi
    fi
}

# Completion et inbox sont publies dans une seule transaction. BLOCKED et
# INFO_REQUIRED revendiquent le meme decision_id que send.sh/report-master.sh,
# ce qui supprime seulement un reveil duplique vers la meme cible.
PUBLISH_OUTPUT=$(python3 "$BUS_PROTOCOL" terminal \
    --from-agent "$FROM_AGENT" \
    --to-agent "$TO_AGENT" \
    --event "$SIGNAL_TYPE" \
    --source-turn-id "$TURN_ID" \
    --task-id "$TASK_ID" \
    --cycle "$CYCLE" \
    --correlation-id "$CORRELATION_ID" \
    --requester "$REQUESTER_ID" \
    --owner "$OWNER_ID" \
    --origin="$TURN_ORIGIN" \
    --signal="$SIGNAL" \
    --completion-maxlen "${STREAM_MAXLEN:-1000}" \
    --inbox-maxlen "${IO_STREAM_MAXLEN:-10000}" \
    --ttl "${TERMINAL_DEDUP_TTL:-604800}")
PUBLISH_RC=$?
IFS='|' read -r PUBLISH_STATE COMPLETION_ID INBOX_STATE MSG_ID \
    EVENT_ID DECISION_ID <<< "$PUBLISH_OUTPUT"
if [ "$PUBLISH_RC" -ne 0 ]; then
    if [ "$PUBLISH_RC" -eq 3 ]; then
        echo "refused: $TO_AGENT event=$SIGNAL_TYPE task=$TASK_ID cycle=$CYCLE corr=$CORRELATION_ID state=NOT_DELIVERED" >&2
        echo "remedy: this terminal slot is already consumed by a different payload; the slot is turn-independent (A9) — open a new CYCLE/CORR then re-emit" >&2
        exit 3
    fi
    exit "$PUBLISH_RC"
fi

# Le stream completion fait foi, y compris lorsque le reveil inbox etait deja
# represente par le rapport bloquant. Fermer l'obligation seulement apres le
# retour atomique positif du publisher.
close_obligation

if [ "$PUBLISH_STATE" = "REPLAY" ]; then
    case "$INBOX_STATE" in
        ALREADY_DELIVERED)
            echo "replay: $TO_AGENT event=$SIGNAL_TYPE event_id=$EVENT_ID decision_id=$DECISION_ID task=$TASK_ID cycle=$CYCLE corr=$CORRELATION_ID turn=$TURN_ID state=ALREADY_DELIVERED${OBLIGATION_STATE}"
            exit 0
            ;;
        ALREADY_SUPPRESSED_BY_DECISION)
            echo "replay: $TO_AGENT event=$SIGNAL_TYPE event_id=$EVENT_ID decision_id=$DECISION_ID task=$TASK_ID cycle=$CYCLE corr=$CORRELATION_ID turn=$TURN_ID state=ALREADY_SUPPRESSED_BY_DECISION${OBLIGATION_STATE}"
            exit 0
            ;;
        *)
            echo "publish-error: invalid replay state '$INBOX_STATE'" >&2
            exit 1
            ;;
    esac
fi
[ "$PUBLISH_STATE" = "CREATED" ] || {
    echo "publish-error: invalid terminal result '$PUBLISH_STATE'" >&2
    exit 1
}

if [ "$INBOX_STATE" = "SUPPRESSED_BY_DECISION" ]; then
    echo "ok: $TO_AGENT completion=$COMPLETION_ID event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=SUPPRESSED_BY_DECISION${OBLIGATION_STATE}"
    exit 0
fi
if [ "$INBOX_STATE" != "DELIVERED" ] || [ -z "$MSG_ID" ]; then
    echo "publish-error: completion stored but inbox result is inconsistent" >&2
    exit 1
fi

if ! tmux has-session -t "=$(agent_session_name "$TO_AGENT")" 2>/dev/null; then
    echo "queued: $TO_AGENT $MSG_ID event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=ORPHANED${OBLIGATION_STATE}" >&2
    exit 2
fi

# Un terminal destiné à un membre de triangle qui n'est pas son coordinateur
# n'ouvre AUCUN tour chez lui (règle anti-boucle : un seul point de décision).
# Il est parqué dans son stream terminals et annexé à son prochain vrai tour.
# Annoncer DELIVERED laisserait croire à une prise en charge immédiate.
# A6 : le format d'ID reste dans lib.sh — triangle_master_id retourne 0
# uniquement pour un membre de triangle qui n'est pas le coordinateur.
if triangle_master_id "$TO_AGENT" >/dev/null; then
    echo "ok: $TO_AGENT $MSG_ID event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=PARKED_NO_WAKE${OBLIGATION_STATE}"
    exit 0
fi

echo "ok: $TO_AGENT $MSG_ID event_id=$EVENT_ID decision_id=$DECISION_ID corr=$CORRELATION_ID turn=$TURN_ID state=DELIVERED${OBLIGATION_STATE}"
