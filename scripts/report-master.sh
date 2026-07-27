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

if [ -z "${TURN_ID:-}" ]; then
    TURN_ID=$($REDIS_CLI HGET "$(agent_status_key "$FROM_AGENT")" current_turn_id 2>/dev/null || true)
fi
TURN_ID="${TURN_ID:-$(cat /proc/sys/kernel/random/uuid)}"
ORIGIN="${TURN_ORIGIN:-${CURRENT_TURN_ORIGIN:-unknown}}"
SOURCE_CORR="${CORRELATION_ID:-none}"
ARTIFACT="${ARTIFACT:-NONE}"
TESTS="${TESTS:-NOT_RUN}"
NEXT="${NEXT:-NONE}"
DURATION="${DURATION:-NON_MESURÉ}"
DETAIL="STATUS=$STATUS|SUMMARY=$SUMMARY|ARTIFACT=$ARTIFACT|TESTS=$TESTS|NEXT=$NEXT|DURATION=$DURATION|TURN_ID=$TURN_ID|ORIGIN=$ORIGIN|SOURCE_CORR=$SOURCE_CORR"

# Canal de supervision dédié : aucun champ prompt, donc aucun réveil modèle.
# Le Master consultera ces rapports lors de son prochain vrai tour.
REPORT_ID=$($REDIS_CLI XADD "agent:${MASTER_ID}:reports" \
    MAXLEN '~' "${IO_STREAM_MAXLEN:-10000}" '*' \
    from_agent "$FROM_AGENT" \
    to_agent "$MASTER_ID" \
    event "MASTER_REPORT" \
    classification "supervision" \
    correlation_id "turn-$TURN_ID" \
    turn_id "$TURN_ID" \
    status "$STATUS" \
    summary "$SUMMARY" \
    artifact "$ARTIFACT" \
    tests "$TESTS" \
    next "$NEXT" \
    duration "$DURATION" \
    origin "$ORIGIN" \
    source_correlation "$SOURCE_CORR" \
    detail "$DETAIL" \
    timestamp "$(date +%s)" 2>/dev/null)
[ -n "$REPORT_ID" ] || {
    echo "ko: MASTER_REPORT persistence failed" >&2
    exit 1
}
DELIVERY_STATE="STORED"

NOW=$(date +%s)
$REDIS_CLI HSET "$(agent_status_key "$FROM_AGENT")" \
    last_master_report_id "$TURN_ID" \
    last_master_report_at "$NOW" \
    last_master_report_status "$STATUS" \
    last_master_report_delivery "$DELIVERY_STATE" \
    last_master_report_target "$MASTER_ID" >/dev/null || {
    echo "warning: report delivered but local report state was not recorded" >&2
    exit 2
}

echo "master-report: from=$FROM_AGENT to=$MASTER_ID turn=$TURN_ID state=$DELIVERY_STATE"
