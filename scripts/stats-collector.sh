#!/bin/bash
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Stats Collector - Merge Git + Redis stats
# Usage: ./stats-collector.sh [agent_id]
#

POOL="$BASE_DIR/pool-requests"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

# Count files for an agent
count_files() {
    local agent=$1
    local type=$2
    local status=$3

    case "$type" in
        PR-DOC)
            if [ "$status" = "done" ]; then
                ls "$POOL/done/PR-DOC-$agent-"*.md 2>/dev/null | wc -l | tr -d ' '
            else
                ls "$POOL/pending/PR-DOC-$agent-"*.md 2>/dev/null | wc -l | tr -d ' '
            fi
            ;;
        PR-SPEC)
            if [ "$status" = "done" ]; then
                ls "$POOL/done/PR-SPEC-$agent-"*.md 2>/dev/null | wc -l | tr -d ' '
            else
                ls "$POOL/pending/PR-SPEC-$agent-"*.md 2>/dev/null | wc -l | tr -d ' '
            fi
            ;;
        PR-TEST)
            if [ "$status" = "done" ]; then
                ls "$POOL/done/PR-TEST-$agent-"*.md 2>/dev/null | wc -l | tr -d ' '
            else
                pending=$(ls "$POOL/pending/PR-TEST-$agent-"*.md 2>/dev/null | wc -l | tr -d ' ')
                tests=$(ls "$POOL/tests/PR-TEST-$agent-"*.json 2>/dev/null | wc -l | tr -d ' ')
                echo $((pending + tests))
            fi
            ;;
    esac
}

# Get Redis status for agent
get_redis_status() {
    local agent=$1
    redis-cli HGET ma:agents "$agent" 2>/dev/null
}

# Update merged stats in Redis
update_stats() {
    local agent=$1

    # Get file counts
    local doc_done=$(count_files "$agent" "PR-DOC" "done")
    local doc_pending=$(count_files "$agent" "PR-DOC" "pending")
    local spec_done=$(count_files "$agent" "PR-SPEC" "done")
    local spec_pending=$(count_files "$agent" "PR-SPEC" "pending")
    local test_done=$(count_files "$agent" "PR-TEST" "done")
    local test_pending=$(count_files "$agent" "PR-TEST" "pending")

    # Get Redis status
    local redis_data=$(get_redis_status "$agent")
    local redis_status="stopped"
    local redis_task="null"
    local redis_queue="0"

    if [ -n "$redis_data" ]; then
        redis_status=$(echo "$redis_data" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('status','stopped'))" 2>/dev/null || echo "stopped")
        redis_task=$(echo "$redis_data" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('current_task') or 'null')" 2>/dev/null || echo "null")
    fi

    redis_queue=$(redis-cli LLEN "ma:inject:$agent" 2>/dev/null || echo "0")

    # Calculate tasks_completed based on agent role
    local tasks_done=0
    case "$agent" in
        201)
            # Doc Generator creates ALL PR-DOC (for 300-303)
            tasks_done=$(ls "$POOL/done/PR-DOC-"*.md 2>/dev/null | wc -l | tr -d ' ')
            ;;
        200)
            # Explorer creates ALL PR-SPEC (for 300-303)
            tasks_done=$(ls "$POOL/done/PR-SPEC-"*.md 2>/dev/null | wc -l | tr -d ' ')
            ;;
        501)
            # Test Creator creates ALL PR-TEST
            tasks_done=$(ls "$POOL/done/PR-TEST-"*.md 2>/dev/null | wc -l | tr -d ' ')
            ;;
        300|301|302|303)
            # Devs process their own PR-SPEC
            tasks_done=$spec_done
            ;;
        *) tasks_done=0 ;;
    esac

    # Store merged stats
    local stats_json=$(cat <<EOF
{
    "agent_id": "$agent",
    "git_doc_done": $doc_done,
    "git_doc_pending": $doc_pending,
    "git_spec_done": $spec_done,
    "git_spec_pending": $spec_pending,
    "git_test_done": $test_done,
    "git_test_pending": $test_pending,
    "tasks_completed": $tasks_done,
    "redis_status": "$redis_status",
    "redis_task": "$redis_task",
    "redis_queue": $redis_queue,
    "updated_at": "$(date -Iseconds)"
}
EOF
)

    redis-cli HSET ma:stats "$agent" "$stats_json" > /dev/null

    # Also update the main agents hash with correct tasks_completed
    if [ -n "$redis_data" ]; then
        local updated_agent=$(echo "$redis_data" | python3 -c "
import sys,json
d=json.loads(sys.stdin.read())
d['tasks_completed']=$tasks_done
print(json.dumps(d))
" 2>/dev/null)
        if [ -n "$updated_agent" ]; then
            redis-cli HSET ma:agents "$agent" "$updated_agent" > /dev/null
        fi
    fi

    echo "$stats_json"
}

# Display stats for one agent
show_agent_stats() {
    local agent=$1
    local stats=$(redis-cli HGET ma:stats "$agent" 2>/dev/null)

    if [ -z "$stats" ]; then
        echo "No stats for agent $agent"
        return
    fi

    echo "$stats" | python3 -c "
import sys,json
d=json.loads(sys.stdin.read())
print(f\"Agent {d['agent_id']}:\")
print(f\"  Status: {d['redis_status']} | Task: {d['redis_task']} | Queue: {d['redis_queue']}\")
print(f\"  PR-DOC:  {d['git_doc_done']:>4} done, {d['git_doc_pending']:>4} pending\")
print(f\"  PR-SPEC: {d['git_spec_done']:>4} done, {d['git_spec_pending']:>4} pending\")
print(f\"  PR-TEST: {d['git_test_done']:>4} done, {d['git_test_pending']:>4} pending\")
print(f\"  Tasks completed: {d['tasks_completed']}\")
"
}

# Main
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo -e "${CYAN}              STATS COLLECTOR                       ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo ""

AGENTS="000 100 200 201 203 300 301 302 303 400 500 501 502 600"

if [ -n "$1" ]; then
    # Single agent
    echo -e "${BLUE}Collecting stats for agent $1...${NC}"
    update_stats "$1" > /dev/null
    show_agent_stats "$1"
else
    # All agents
    echo -e "${BLUE}Collecting stats for all agents...${NC}"
    echo ""

    for agent in $AGENTS; do
        update_stats "$agent" > /dev/null
    done

    echo -e "${GREEN}Stats updated!${NC}"
    echo ""

    # Summary table
    printf "               │ REDIS │    PR-DOC     │    PR-SPEC    │    PR-TEST    │\n"
    printf "%-5s %-8s │ %5s │ %5s  %5s  │ %5s  %5s  │ %5s  %5s  │\n" "ID" "STATUS" "QUEUE" "PEND" "DONE" "PEND" "DONE" "PEND" "DONE"
    printf "%-5s %-8s │ %5s │ %5s  %5s  │ %5s  %5s  │ %5s  %5s  │\n" "-----" "--------" "-----" "-----" "-----" "-----" "-----" "-----" "-----"

    for agent in $AGENTS; do
        stats=$(redis-cli HGET ma:stats "$agent" 2>/dev/null)
        if [ -n "$stats" ]; then
            echo "$stats" | python3 -c "
import sys,json
d=json.loads(sys.stdin.read())
status = d['redis_status'][:8]
queue = d['redis_queue']
doc_pend = d['git_doc_pending']
doc_done = d['git_doc_done']
spec_pend = d['git_spec_pending']
spec_done = d['git_spec_done']
test_pend = d['git_test_pending']
test_done = d['git_test_done']
print(f\"{d['agent_id']:<5} {status:<8} │ {queue:>5} │ {doc_pend:>5}  {doc_done:>5}  │ {spec_pend:>5}  {spec_done:>5}  │ {test_pend:>5}  {test_done:>5}  │\")
"
        fi
    done

    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"

    # Totals
    total_spec_done=$(ls "$POOL/done/PR-SPEC-"*.md 2>/dev/null | wc -l | tr -d ' ')
    total_spec_pend=$(ls "$POOL/pending/PR-SPEC-"*.md 2>/dev/null | wc -l | tr -d ' ')
    total_test_done=$(ls "$POOL/done/PR-TEST-"*.md 2>/dev/null | wc -l | tr -d ' ')
    total_doc_done=$(ls "$POOL/done/PR-DOC-"*.md 2>/dev/null | wc -l | tr -d ' ')

    echo -e "PR-DOC:  ${GREEN}$total_doc_done done${NC}"
    echo -e "PR-SPEC: ${GREEN}$total_spec_done done${NC}, ${YELLOW}$total_spec_pend pending${NC}"
    echo -e "PR-TEST: ${GREEN}$total_test_done done${NC}"
fi
