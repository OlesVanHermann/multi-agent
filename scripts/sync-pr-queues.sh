#!/bin/bash
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Sync PR files with Redis queues
# Only adds PRs that are not already in the queue
#

POOL_DIR="$BASE_DIR/pool-requests"

echo "=== Syncing PR files → Redis queues ==="
echo ""

sync_pr_to_queue() {
    local pattern="$1"
    local queue="$2"
    local label="$3"

    # Get current queue contents
    local queue_contents=$(redis-cli LRANGE "$queue" 0 -1 | sort -u)

    local added=0
    local skipped=0

    for f in $POOL_DIR/pending/$pattern 2>/dev/null; do
        [ -f "$f" ] || continue
        pr=$(basename "$f" .md)

        # Check if already in queue
        if echo "$queue_contents" | grep -q "^${pr}$"; then
            ((skipped++))
        else
            redis-cli RPUSH "$queue" "$pr" > /dev/null
            ((added++))
        fi
    done

    local total=$(redis-cli LLEN "$queue")
    echo "$label: +$added new (skipped $skipped duplicates) → queue: $total"
}

# PR-SPEC → 3XX agents
for agent in 300 301 302 303; do
    sync_pr_to_queue "PR-SPEC-${agent}-*.md" "ma:inject:${agent}" "Agent $agent (PR-SPEC)"
done

echo ""

# PR-TEST → 501
sync_pr_to_queue "PR-TEST-*.md" "ma:inject:501" "Agent 501 (PR-TEST)"

echo ""

# PR-FIX → 3XX agents (priority)
for agent in 300 301 302 303; do
    count=$(ls "$POOL_DIR/pending/PR-FIX-${agent}-"*.md 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        sync_pr_to_queue "PR-FIX-${agent}-*.md" "ma:inject:${agent}" "Agent $agent (PR-FIX)"
    fi
done

echo ""
echo "=== Sync complete ==="
