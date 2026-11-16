#!/bin/bash
# report-master.sh — Rapport de fin de tour obligatoire au coordinateur 1XX.
# Usage: ./scripts/report-master.sh <STATUS> <résumé>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/redis.sh"
source "$SCRIPT_DIR/lib.sh"

STATUS="${1:-}"
shift 2>/dev/null || true
SUMMARY="$*"

case "$STATUS" in
    SUCCESS|PARTIAL|FAILED|BLOCKED|INFO_REQUIRED) ;;
    *)
        echo "Usage: $0 SUCCESS|PARTIAL|FAILED|BLOCKED|INFO_REQUIRED <résumé>" >&2
        exit 1
        ;;
esac
[ -n "$SUMMARY" ] || {
    echo "Error: a factual summary is required" >&2
    exit 1
}

if [ -n "$TMUX" ]; then
    SESSION_NAME=$(tmux display-message -p '#S' 2>/dev/null || true)
    if [[ "$SESSION_NAME" =~ ^agent-([0-9]+-[0-9]+)$ ]]; then
        FROM_AGENT="${BASH_REMATCH[1]}"
    fi
fi
FROM_AGENT="${FROM_AGENT:-}"
is_valid_agent_id "$FROM_AGENT" || {
    echo "Error: report-master.sh must run from an agent triangle session" >&2
    exit 1
}

MASTER_ID=$(triangle_master_id "$FROM_AGENT") || {
    echo "skipped: $FROM_AGENT has no distinct triangle Master"
    exit 0
}

BUS_PROTOCOL="$SCRIPT_DIR/agent-bridge/bus_protocol.py"
CONTEXT_OUTPUT=$(python3 "$BUS_PROTOCOL" context \
    --kind report \
    --from-agent "$FROM_AGENT" \
    --to-agent "$MASTER_ID" \
    --event "$STATUS" \
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
    REQUESTER_ID OWNER_ID ORIGIN <<< "$CONTEXT_OUTPUT"
[ "$CONTEXT_KIND" = "CONTEXT" ] || {
    echo "publish-error: invalid context response" >&2
    exit 1
}

ARTIFACT="${ARTIFACT:-NONE}"
TESTS="${TESTS:-NOT_RUN}"
NEXT="${NEXT:-NONE}"
DURATION="${DURATION:-NON_MESURÉ}"

# MASTER_REPORT et, pour un blocage, DECISION_REQUIRED sont publies dans une
# seule transaction Redis. Le ledger par tour rend le rejeu idempotent et
# refuse un second contenu sous le meme TURN_ID.
PUBLISH_OUTPUT=$(python3 "$BUS_PROTOCOL" report \
    --from-agent "$FROM_AGENT" \
    --to-agent "$MASTER_ID" \
    --event "$STATUS" \
    --source-turn-id "$TURN_ID" \
    --task-id "$TASK_ID" \
    --cycle "$CYCLE" \
    --correlation-id "$CORRELATION_ID" \
    --requester "$REQUESTER_ID" \
    --owner "$OWNER_ID" \
    --origin="$ORIGIN" \
    --summary="$SUMMARY" \
    --artifact="$ARTIFACT" \
    --tests="$TESTS" \
    --next="$NEXT" \
    --duration="$DURATION" \
    --report-maxlen "${IO_STREAM_MAXLEN:-10000}" \
    --inbox-maxlen "${IO_STREAM_MAXLEN:-10000}" \
    --ttl "${TERMINAL_DEDUP_TTL:-604800}")
PUBLISH_RC=$?
IFS='|' read -r PUBLISH_STATE REPORT_STREAM_ID REPORT_ID EVENT_ID \
    WAKE_STATE WAKE_STREAM_ID DECISION_ID <<< "$PUBLISH_OUTPUT"
if [ "$PUBLISH_RC" -ne 0 ]; then
    if [ "$PUBLISH_RC" -eq 3 ]; then
        echo "refused: MASTER_REPORT turn=$TURN_ID state=CONFLICT_NOT_STORED" >&2
    fi
    exit "$PUBLISH_RC"
fi

case "$PUBLISH_STATE" in
    CREATED) REPORT_STATE="STORED" ;;
    REPLAY) REPORT_STATE="ALREADY_STORED" ;;
    *)
        echo "publish-error: invalid report result '$PUBLISH_STATE'" >&2
        exit 1
        ;;
esac

echo "master-report: from=$FROM_AGENT to=$MASTER_ID turn=$TURN_ID state=$REPORT_STATE wake=$WAKE_STATE report_id=$REPORT_ID report_stream_id=$REPORT_STREAM_ID event_id=$EVENT_ID wake_stream_id=$WAKE_STREAM_ID decision_id=$DECISION_ID"
