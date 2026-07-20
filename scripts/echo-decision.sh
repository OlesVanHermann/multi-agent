#!/bin/bash
# G6 — mesure la décision humaine aval d'un rapport Contradictor.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/redis.sh"
source "$SCRIPT_DIR/lib.sh"

ECHO_ID="${1:?usage: echo-decision.sh <NNN-2XX> <followed|ignored> <task> <outcome>}"
DECISION="${2:-}"
TASK_ID="${3:-}"
OUTCOME="${4:-unknown}"
ECHO_PREFIX="${ECHO_ID%%-*}"
ECHO_SUFFIX="${ECHO_ID#*-}"
if ! is_valid_agent_id "$ECHO_ID" || [ "$ECHO_PREFIX" = "$ECHO_ID" ] \
        || [ "$ECHO_SUFFIX" -lt 200 ] 2>/dev/null || [ "$ECHO_SUFFIX" -gt 299 ] 2>/dev/null \
        || [[ ! "$DECISION" =~ ^(followed|ignored)$ ]] || [ -z "$TASK_ID" ]; then
    echo "usage: echo-decision.sh <NNN-2XX> <followed|ignored> <task> <outcome>" >&2
    exit 2
fi
$REDIS_CLI XADD "wal" MAXLEN '~' "${WAL_MAXLEN:-100000}" '*' \
    event "critic_${DECISION}" agent_id "$ECHO_ID" task_id "$TASK_ID" \
    downstream_outcome "$OUTCOME" ts "$(date +%s)" >/dev/null
echo "ok: critic_${DECISION} task=$TASK_ID outcome=$OUTCOME"
