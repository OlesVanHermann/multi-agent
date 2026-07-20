#!/bin/bash
# G5 — réponse terminale sourcée de l'Ami vers le worker appelant.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/redis.sh"
source "$SCRIPT_DIR/lib.sh"

TO_AGENT="${1:?usage: help-result.sh <worker> <RESOLU|NOT_FOUND> <artifact>}"
RESULT="${2:-}"
ARTIFACT="${3:-}"
TASK_ID="${TASK_ID:?TASK_ID requis}"
CYCLE="${CYCLE:?CYCLE requis}"
CORRELATION_ID="${CORRELATION_ID:?CORRELATION_ID requis}"
FROM_AGENT="${FROM_AGENT:-}"

FROM_PREFIX="${FROM_AGENT%%-*}"
FROM_SUFFIX="${FROM_AGENT#*-}"
TO_PREFIX="${TO_AGENT%%-*}"
TO_SUFFIX="${TO_AGENT#*-}"
if ! is_valid_agent_id "$FROM_AGENT" || ! is_valid_agent_id "$TO_AGENT" \
        || [ "$FROM_PREFIX" = "$FROM_AGENT" ] || [ "$TO_PREFIX" = "$TO_AGENT" ] \
        || [ "$FROM_SUFFIX" -lt 800 ] 2>/dev/null || [ "$FROM_SUFFIX" -gt 899 ] 2>/dev/null \
        || [ "$TO_SUFFIX" -lt 300 ] 2>/dev/null || [ "$TO_SUFFIX" -gt 399 ] 2>/dev/null \
        || [ "$FROM_PREFIX" != "$TO_PREFIX" ]; then
    echo "PROTOCOL_ERROR: réponse Ami/worker hors triangle" >&2
    exit 2
fi
if [[ ! "$RESULT" =~ ^(RESOLU|NOT_FOUND)$ ]] || [ ! -f "$ARTIFACT" ]; then
    echo "PROTOCOL_ERROR: résultat ou artefact invalide" >&2
    exit 2
fi
SHA256=$(sha256sum "$ARTIFACT" | awk '{print $1}')
EVENT="help_resolved"
[ "$RESULT" = "NOT_FOUND" ] && EVENT="help_notfound"
$REDIS_CLI XADD "wal" MAXLEN '~' "${WAL_MAXLEN:-100000}" '*' \
    event "$EVENT" agent_id "$FROM_AGENT" task_id "$TASK_ID" cycle "$CYCLE" \
    correlation_id "$CORRELATION_ID" source_path "$ARTIFACT" sha256 "$SHA256" \
    ts "$(date +%s)" >/dev/null

MESSAGE="FROM:${FROM_AGENT}|EVENT:ARTIFACT_READY|TASK:${TASK_ID}|CYCLE:${CYCLE}|CORR:${CORRELATION_ID}|ARTIFACT:${ARTIFACT}|SHA256:${SHA256}|DETAIL:${RESULT}"
FROM_AGENT="$FROM_AGENT" TASK_ID="$TASK_ID" CYCLE="$CYCLE" \
CORRELATION_ID="$CORRELATION_ID" "$SCRIPT_DIR/send.sh" "$TO_AGENT" "$MESSAGE"
