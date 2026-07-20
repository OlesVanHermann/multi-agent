#!/bin/bash
# G5 — appel borné d'un worker vers l'Ami NNN-805.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/redis.sh"
source "$SCRIPT_DIR/lib.sh"

AMI_ID="${1:?usage: help.sh <NNN-805> <demande> <deja_lu> <ambigu> <oui|non>}"
DEMANDE="${2:-}"
DEJA_LU="${3:-}"
AMBIGU="${4:-}"
BLOQUANT="${5:-}"
TASK_ID="${TASK_ID:?TASK_ID requis}"
CYCLE="${CYCLE:?CYCLE requis}"
CORRELATION_ID="${CORRELATION_ID:-$(cat /proc/sys/kernel/random/uuid)}"

AMI_PREFIX="${AMI_ID%%-*}"
AMI_SUFFIX="${AMI_ID#*-}"
if ! is_valid_agent_id "$AMI_ID" || [ "$AMI_PREFIX" = "$AMI_ID" ] \
        || [ "$AMI_SUFFIX" -lt 800 ] 2>/dev/null || [ "$AMI_SUFFIX" -gt 899 ] 2>/dev/null; then
    echo "PROTOCOL_ERROR: cible attendue NNN-8XX" >&2
    exit 2
fi
if [ -z "$DEMANDE" ] || [ -z "$DEJA_LU" ] || [ -z "$AMBIGU" ] || [[ ! "$BLOQUANT" =~ ^(oui|non)$ ]]; then
    echo "PROTOCOL_ERROR: DEMANDE, DEJA_LU, AMBIGU et BLOQUANT=oui|non requis" >&2
    exit 2
fi

FROM_AGENT="${FROM_AGENT:-}"
if [ -z "$FROM_AGENT" ] && [ -n "${TMUX:-}" ]; then
    SESSION_NAME=$(tmux display-message -p '#S' 2>/dev/null || true)
    SESSION_PREFIX="agent-"
    if [[ "$SESSION_NAME" == "$SESSION_PREFIX"* ]]; then
        CANDIDATE="${SESSION_NAME#${SESSION_PREFIX}}"
        if is_valid_agent_id "$CANDIDATE"; then
            FROM_AGENT="$CANDIDATE"
        fi
    fi
fi
FROM_PREFIX="${FROM_AGENT%%-*}"
FROM_SUFFIX="${FROM_AGENT#*-}"
if ! is_valid_agent_id "$FROM_AGENT" || [ "$FROM_PREFIX" = "$FROM_AGENT" ] \
        || [ "$FROM_SUFFIX" -lt 300 ] 2>/dev/null || [ "$FROM_SUFFIX" -gt 399 ] 2>/dev/null \
        || [ "$FROM_PREFIX" != "$AMI_PREFIX" ]; then
    echo "PROTOCOL_ERROR: seul un worker 3XX du même triangle peut appeler l'Ami" >&2
    exit 2
fi

RATE_KEY="help-once:${FROM_AGENT}:${TASK_ID}:${CYCLE}"
CLAIM=$($REDIS_CLI SET "$RATE_KEY" "$CORRELATION_ID" NX EX 86400 2>/dev/null || true)
if [ "$CLAIM" != "OK" ]; then
    echo "PROTOCOL_ERROR: un HELP_REQUEST existe déjà pour cette tâche et ce cycle" >&2
    exit 3
fi

$REDIS_CLI XADD "wal" MAXLEN '~' "${WAL_MAXLEN:-100000}" '*' \
    event help_request agent_id "$FROM_AGENT" task_id "$TASK_ID" cycle "$CYCLE" \
    correlation_id "$CORRELATION_ID" ambigu "$AMBIGU" ts "$(date +%s)" >/dev/null

MESSAGE="FROM:${FROM_AGENT}|EVENT:HELP_REQUEST|TASK:${TASK_ID}|CYCLE:${CYCLE}|CORR:${CORRELATION_ID}
DEMANDE : ${DEMANDE}
DEJA_LU : ${DEJA_LU}
AMBIGU : ${AMBIGU}
BLOQUANT : ${BLOQUANT}"
FROM_AGENT="$FROM_AGENT" TASK_ID="$TASK_ID" CYCLE="$CYCLE" \
CORRELATION_ID="$CORRELATION_ID" "$SCRIPT_DIR/send.sh" "$AMI_ID" "$MESSAGE"
