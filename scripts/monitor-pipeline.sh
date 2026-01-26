#!/bin/bash
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Monitor Pipeline - Push idle agents with pending work
# Usage: ./monitor-pipeline.sh [interval_seconds]
#

POOL="$BASE_DIR/pool-requests"
INTERVAL=${1:-30}

echo "Pipeline Monitor - checking every ${INTERVAL}s"
echo "Press Ctrl+C to stop"
echo ""

while true; do
    # Count pending work
    SPEC_300=$(ls "$POOL/pending/PR-SPEC-300-"*.md 2>/dev/null | wc -l | tr -d ' ')
    SPEC_301=$(ls "$POOL/pending/PR-SPEC-301-"*.md 2>/dev/null | wc -l | tr -d ' ')
    SPEC_302=$(ls "$POOL/pending/PR-SPEC-302-"*.md 2>/dev/null | wc -l | tr -d ' ')
    SPEC_303=$(ls "$POOL/pending/PR-SPEC-303-"*.md 2>/dev/null | wc -l | tr -d ' ')
    TEST_PEND=$(ls "$POOL/pending/PR-TEST-"*.md 2>/dev/null | wc -l | tr -d ' ')

    # Get agent statuses
    STATUS_300=$(redis-cli HGET ma:agents 300 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status','stopped'))" 2>/dev/null || echo "stopped")
    STATUS_301=$(redis-cli HGET ma:agents 301 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status','stopped'))" 2>/dev/null || echo "stopped")
    STATUS_302=$(redis-cli HGET ma:agents 302 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status','stopped'))" 2>/dev/null || echo "stopped")
    STATUS_303=$(redis-cli HGET ma:agents 303 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status','stopped'))" 2>/dev/null || echo "stopped")
    STATUS_501=$(redis-cli HGET ma:agents 501 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status','stopped'))" 2>/dev/null || echo "stopped")
    STATUS_100=$(redis-cli HGET ma:agents 100 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status','stopped'))" 2>/dev/null || echo "stopped")

    PUSHED=""

    # Push 300 if idle with pending work
    if [ "$STATUS_300" = "idle" ] && [ "$SPEC_300" -gt 0 ]; then
        redis-cli RPUSH "ma:inject:300" "go" > /dev/null
        PUSHED="$PUSHED 300"
    fi

    # Push 301 if idle with pending work
    if [ "$STATUS_301" = "idle" ] && [ "$SPEC_301" -gt 0 ]; then
        redis-cli RPUSH "ma:inject:301" "go" > /dev/null
        PUSHED="$PUSHED 301"
    fi

    # Push 302 if idle with pending work
    if [ "$STATUS_302" = "idle" ] && [ "$SPEC_302" -gt 0 ]; then
        redis-cli RPUSH "ma:inject:302" "go" > /dev/null
        PUSHED="$PUSHED 302"
    fi

    # Push 303 if idle with pending work
    if [ "$STATUS_303" = "idle" ] && [ "$SPEC_303" -gt 0 ]; then
        redis-cli RPUSH "ma:inject:303" "go" > /dev/null
        PUSHED="$PUSHED 303"
    fi

    # Push 100 to dispatch to 501 if 501 is idle and there's pending work
    if [ "$STATUS_501" = "idle" ] && [ "$TEST_PEND" -gt 0 ] && [ "$STATUS_100" = "idle" ]; then
        redis-cli RPUSH "ma:inject:100" "go" > /dev/null
        PUSHED="$PUSHED 100→501"
    fi

    # Display status
    NOW=$(date +%H:%M:%S)
    TOTAL_SPEC=$((SPEC_300 + SPEC_301 + SPEC_302 + SPEC_303))

    if [ -n "$PUSHED" ]; then
        echo "[$NOW] SPEC:$TOTAL_SPEC TEST:$TEST_PEND | Pushed:$PUSHED"
    else
        echo "[$NOW] SPEC:$TOTAL_SPEC TEST:$TEST_PEND | All working"
    fi

    sleep $INTERVAL
done
