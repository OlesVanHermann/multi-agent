#!/bin/bash
#
# Start all agents for Super-Agent v2.0
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
LOGS_DIR="$BASE_DIR/logs"
PIDS_DIR="$LOGS_DIR/pids"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

# ===========================================
# CONFIGURATION DES AGENTS
# ===========================================
# Format: "ID:ROLE:DESCRIPTION"
# Customize this list for your project
AGENTS=(
    "000:super-master:Super-Master - Coordination globale"
    "100:master:Master - Dispatch des tâches"
    "200:slave:Explorer - Analyse et création SPEC"
    "300:slave:Developer - Implémentation"
    "400:slave:Merge - Fusion Git"
    "500:slave:Test - Validation"
    "600:slave:Release - Publication"
)

PROJECT="default"

# ===========================================
# FUNCTIONS
# ===========================================

log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_ok() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

ensure_redis() {
    if ! redis-cli ping &>/dev/null; then
        log_info "Starting Redis..."
        redis-server --daemonize yes --port 6379
        sleep 1
        if redis-cli ping &>/dev/null; then
            log_ok "Redis started"
        else
            log_error "Failed to start Redis"
            exit 1
        fi
    else
        log_ok "Redis already running"
    fi
}

start_agent() {
    local id=$1
    local role=$2
    local desc=$3

    local log_dir="$LOGS_DIR/$id"
    mkdir -p "$log_dir"

    # Check if already running
    if [ -f "$PIDS_DIR/$id.pid" ]; then
        local pid=$(cat "$PIDS_DIR/$id.pid")
        if ps -p "$pid" &>/dev/null; then
            log_warn "Agent $id already running (PID: $pid)"
            return
        fi
    fi

    # Start agent
    cd "$BASE_DIR"
    local runner="core/agent-runner/agent_runner.py"

    python3 "$runner" \
        --role "$role" \
        --id "$id" \
        --project "$PROJECT" \
        > "$log_dir/runner.log" 2>&1 &

    local pid=$!
    echo "$pid" > "$PIDS_DIR/$id.pid"

    log_ok "Agent $id started (PID: $pid) - $desc"
    echo "     tail -F $log_dir/claude.log"
}

stop_agent() {
    local id=$1

    if [ -f "$PIDS_DIR/$id.pid" ]; then
        local pid=$(cat "$PIDS_DIR/$id.pid")
        if ps -p "$pid" &>/dev/null; then
            kill "$pid" 2>/dev/null
            log_ok "Agent $id stopped (PID: $pid)"
        fi
        mv "$PIDS_DIR/$id.pid" "$BASE_DIR/removed/$id.pid.$(date +%s)" 2>/dev/null || true
    fi
}

cmd_start() {
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}         SUPER-AGENT v2.0 - STARTING               ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo ""

    mkdir -p "$LOGS_DIR" "$PIDS_DIR"

    # Start Redis
    ensure_redis

    # Clean only agent states (keep queues intact)
    redis-cli DEL ma:agents > /dev/null
    log_ok "Agent states reset (queues preserved)"

    # Show queue status
    local total_queued=0
    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id role desc <<< "$agent"
        local qlen=$(redis-cli LLEN "ma:inject:$id" 2>/dev/null || echo 0)
        if [ "$qlen" -gt 0 ]; then
            echo "     Queue $id: $qlen tasks pending"
            total_queued=$((total_queued + qlen))
        fi
    done
    if [ "$total_queued" -gt 0 ]; then
        log_info "Total: $total_queued tasks in queues (will resume)"
    fi

    echo ""
    log_info "Starting agents..."
    echo ""

    # Start all agents
    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id role desc <<< "$agent"
        start_agent "$id" "$role" "$desc"
    done

    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}All agents started!${NC}"
    echo ""
    echo "Commands:"
    echo "  $0 status     - Show agent status"
    echo "  $0 stop       - Stop all agents"
    echo "  $0 logs <id>  - Tail agent logs"
    echo "  $0 send <id> <msg> - Send message to agent"
    echo ""
    echo "Logs directory: $LOGS_DIR"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
}

cmd_stop() {
    echo -e "${CYAN}Stopping all agents...${NC}"

    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id role desc <<< "$agent"
        stop_agent "$id"
    done

    # Clean Redis registrations
    redis-cli DEL ma:agents > /dev/null 2>&1

    log_ok "All agents stopped"
}

cmd_status() {
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}                 AGENT STATUS                       ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo ""

    # Redis status
    if redis-cli ping &>/dev/null; then
        echo -e "Redis: ${GREEN}running${NC}"
    else
        echo -e "Redis: ${RED}stopped${NC}"
    fi
    echo ""

    # Get Redis statuses into a temp file
    redis-cli HGETALL "ma:agents" 2>/dev/null | python3 -c "
import sys,json
lines=sys.stdin.read().strip().split('\n')
if lines and lines!=['']:
    i=0
    while i<len(lines)-1:
        try:
            d=json.loads(lines[i+1])
            ctx = d.get('context_remaining', '')
            ctx_str = f'{ctx}%' if ctx else ''
            tasks = d.get('tasks_in_session', '')
            task_text = (d.get('current_task') or 'None').replace('|','-')
            print(f\"{lines[i]}|{d.get('status','?')}|{ctx_str}|{tasks}|{task_text}\")
        except:pass
        i+=2
" > /tmp/agent_states.txt 2>/dev/null || true

    # Agent status
    printf "%-5s %-25s %-12s %-6s %5s %4s  %s\n" "ID" "ROLE" "SESSION" "STATE" "QUEUE" "DONE" "TASK"
    printf "%-5s %-25s %-12s %-6s %5s %4s  %s\n" "-----" "-------------------------" "------------" "------" "-----" "----" "----"

    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id role desc <<< "$agent"

        local proc_status="stopped"
        local proc_color="${RED}"
        local agent_state="-"
        local state_color=""
        local current_task=""
        local session_id="-"

        # Session ID from Redis state (if available)
        local redis_state=$(redis-cli HGET "ma:agents" "$id" 2>/dev/null || echo "{}")
        session_id=$(echo "$redis_state" | python3 -c "import sys,json; d=json.loads(sys.stdin.read() or '{}'); print(d.get('session_id','')[:8] if d.get('session_id') else '-')" 2>/dev/null || echo "-")

        if [ -f "$PIDS_DIR/$id.pid" ]; then
            pid=$(cat "$PIDS_DIR/$id.pid")
            if ps -p "$pid" &>/dev/null; then
                proc_status="run"
                proc_color="${GREEN}"
            fi
        fi

        # Get Redis state for this agent
        local queue_len="0"
        local task_count="0"
        if [ -f /tmp/agent_states.txt ]; then
            state_line=$(grep "^$id|" /tmp/agent_states.txt 2>/dev/null || true)
            if [ -n "$state_line" ]; then
                agent_state=$(echo "$state_line" | cut -d'|' -f2)
                task_count=$(echo "$state_line" | cut -d'|' -f4)
                current_task=$(echo "$state_line" | cut -d'|' -f5-)
                [ -z "$task_count" ] && task_count="0"
                if [ "$agent_state" = "busy" ]; then
                    state_color="${YELLOW}"
                elif [ "$agent_state" = "idle" ]; then
                    state_color="${BLUE}"
                elif [ "$agent_state" = "error" ]; then
                    state_color="${RED}"
                fi
            fi
        fi

        # Get queue length from Redis
        queue_len=$(redis-cli LLEN "ma:inject:$id" 2>/dev/null || echo 0)
        local queue_color=""
        if [ "$queue_len" -gt 50 ]; then
            queue_color="${RED}"
        elif [ "$queue_len" -gt 10 ]; then
            queue_color="${YELLOW}"
        elif [ "$queue_len" -gt 0 ]; then
            queue_color="${GREEN}"
        fi

        # Truncate task to 30 chars, desc to 20 chars
        current_task="${current_task:0:30}"
        local short_desc="${desc:0:20}"

        printf "%-5s %-25s ${proc_color}%-12s${NC} ${state_color}%-6s${NC} ${queue_color}%5s${NC} %4s  %s\n" \
            "$id" "$short_desc" "$proc_status($session_id)" "$agent_state" "$queue_len" "$task_count" "$current_task"
    done

    echo ""
    mv /tmp/agent_states.txt "$BASE_DIR/removed/agent_states.txt.$(date +%s)" 2>/dev/null || true
}

cmd_logs() {
    local id=$1
    if [ -z "$id" ]; then
        log_error "Usage: $0 logs <agent_id>"
        exit 1
    fi

    local log_file="$LOGS_DIR/$id/claude.log"
    if [ -f "$log_file" ]; then
        tail -F "$log_file"
    else
        log_error "Log file not found: $log_file"
        exit 1
    fi
}

cmd_send() {
    local id=$1
    shift
    local msg="$*"

    if [ -z "$id" ] || [ -z "$msg" ]; then
        log_error "Usage: $0 send <agent_id> <message>"
        exit 1
    fi

    redis-cli RPUSH "ma:inject:$id" "$msg" > /dev/null
    log_ok "Message sent to agent $id"
}

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

# ===========================================
# MAIN
# ===========================================

cmd_flush() {
    echo -e "${YELLOW}Flushing all Redis data (queues + states)...${NC}"
    redis-cli FLUSHDB > /dev/null
    log_ok "All Redis data cleared"
}

cmd_queues() {
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}                 QUEUE STATUS                       ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo ""

    local total=0
    for agent in "${AGENTS[@]}"; do
        IFS=':' read -r id role desc <<< "$agent"
        local qlen=$(redis-cli LLEN "ma:inject:$id" 2>/dev/null || echo 0)
        printf "%-6s %-30s %s\n" "$id" "$desc" "$qlen tasks"
        total=$((total + qlen))
    done
    echo ""
    echo -e "Total: ${GREEN}$total${NC} tasks in queues"
}

cmd_stats() {
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}              REAL-TIME STATS                       ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo ""

    local REPO="$BASE_DIR/project"
    local PR_DIR="$BASE_DIR/pool-requests"

    # Stats from code
    echo -e "${YELLOW}=== CODE (server_multiformat.py) ===${NC}"
    if [ -f "$REPO/server_multiformat.py" ]; then
        local excel=$(grep -c "^def excel_\|^async def excel_" "$REPO/server_multiformat.py" 2>/dev/null || echo 0)
        local word=$(grep -c "^def word_\|^async def word_" "$REPO/server_multiformat.py" 2>/dev/null || echo 0)
        local pptx=$(grep -c "^def pptx_\|^async def pptx_" "$REPO/server_multiformat.py" 2>/dev/null || echo 0)
        local pdf=$(grep -c "^def pdf_\|^async def pdf_" "$REPO/server_multiformat.py" 2>/dev/null || echo 0)
        local total=$((excel + word + pptx + pdf))
        printf "%-10s %5d fonctions\n" "Excel:" "$excel"
        printf "%-10s %5d fonctions\n" "Word:" "$word"
        printf "%-10s %5d fonctions\n" "PPTX:" "$pptx"
        printf "%-10s %5d fonctions\n" "PDF:" "$pdf"
        echo "----------------------------"
        printf "%-10s ${GREEN}%5d fonctions${NC}\n" "TOTAL:" "$total"
    else
        echo -e "${RED}server_multiformat.py non trouvé${NC}"
    fi
    echo ""

    # Stats from PR files
    echo -e "${YELLOW}=== PR FILES ===${NC}"
    local spec_pending=$(ls "$PR_DIR/pending"/PR-SPEC-*.md 2>/dev/null | wc -l | tr -d ' ')
    local spec_done=$(ls "$PR_DIR/done"/PR-SPEC-*.md 2>/dev/null | wc -l | tr -d ' ')
    local test_pending=$(ls "$PR_DIR/pending"/PR-TEST-*.md 2>/dev/null | wc -l | tr -d ' ')
    local test_done=$(ls "$PR_DIR/done"/PR-TEST-*.md 2>/dev/null | wc -l | tr -d ' ')
    local doc_pending=$(ls "$PR_DIR/pending"/PR-DOC-*.md 2>/dev/null | wc -l | tr -d ' ')
    local doc_done=$(ls "$PR_DIR/done"/PR-DOC-*.md 2>/dev/null | wc -l | tr -d ' ')
    local fix_pending=$(ls "$PR_DIR/pending"/PR-FIX-*.md 2>/dev/null | wc -l | tr -d ' ')
    local fix_done=$(ls "$PR_DIR/done"/PR-FIX-*.md 2>/dev/null | wc -l | tr -d ' ')
    printf "%-15s %5s pending  %5s done\n" "PR-SPEC:" "$spec_pending" "$spec_done"
    printf "%-15s %5s pending  %5s done\n" "PR-DOC:" "$doc_pending" "$doc_done"
    printf "%-15s %5s pending  %5s done\n" "PR-TEST:" "$test_pending" "$test_done"
    printf "%-15s %5s pending  %5s done\n" "PR-FIX:" "$fix_pending" "$fix_done"
    echo ""

    # Stats from git
    echo -e "${YELLOW}=== GIT COMMITS (branche dev) ===${NC}"
    if [ -d "$REPO/.git" ]; then
        cd "$REPO"
        local commits_dev=$(git rev-list --count dev 2>/dev/null || echo 0)
        local commits_main=$(git rev-list --count main 2>/dev/null || echo 0)
        local ahead=$(git rev-list --count main..dev 2>/dev/null || echo 0)
        printf "%-15s %5d commits\n" "dev:" "$commits_dev"
        printf "%-15s %5d commits\n" "main:" "$commits_main"
        printf "%-15s ${YELLOW}%5d commits${NC} (à merger)\n" "dev ahead:" "$ahead"
    fi
    echo ""

    # Per-repo stats
    echo -e "${YELLOW}=== DEV REPOS (commits non mergés) ===${NC}"
    for format in excel word pptx pdf; do
        local dev_repo="$BASE_DIR/project-$format"
        if [ -d "$dev_repo/.git" ]; then
            cd "$dev_repo"
            local branch="dev-$format"
            local total_commits=$(git rev-list --count "$branch" 2>/dev/null || echo 0)
            printf "%-20s %5d commits\n" "mcp-onlyoffice-$format:" "$total_commits"
        fi
    done
    echo ""
}

case "${1:-start}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    stats)   cmd_stats ;;
    watch)   clear; cmd_status ;;
    logs)    cmd_logs "$2" ;;
    send)    shift; cmd_send "$@" ;;
    flush)   cmd_flush ;;
    queues)  cmd_queues ;;
    sync)    "$SCRIPT_DIR/sync-pr-queues.sh" ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|stats|watch|logs <id>|send <id> <msg>|flush|queues|sync}"
        exit 1
        ;;
esac

# ===========================================
# Orchestrator
# ===========================================
cmd_orchestrator_start() {
    local interval=${1:-60}
    mkdir -p "$LOGS_DIR/orchestrator"
    
    if [ -f "$LOGS_DIR/orchestrator/pid" ]; then
        local pid=$(cat "$LOGS_DIR/orchestrator/pid")
        if ps -p "$pid" &>/dev/null; then
            log_warn "Orchestrator already running (PID: $pid)"
            return
        fi
    fi
    
    "$SCRIPT_DIR/orchestrator.sh" "$interval" >> "$LOGS_DIR/orchestrator/orchestrator.log" 2>&1 &
    echo $! > "$LOGS_DIR/orchestrator/pid"
    log_ok "Orchestrator started (interval: ${interval}s)"
    echo "     Add tasks: echo 'task' >> $SCRIPT_DIR/tasks.txt"
    echo "     View logs: tail -F $LOGS_DIR/orchestrator/orchestrator.log"
}

cmd_orchestrator_stop() {
    if [ -f "$LOGS_DIR/orchestrator/pid" ]; then
        local pid=$(cat "$LOGS_DIR/orchestrator/pid")
        kill "$pid" 2>/dev/null && log_ok "Orchestrator stopped" || log_warn "Orchestrator not running"
        mv "$LOGS_DIR/orchestrator/pid" "$BASE_DIR/removed/orchestrator.pid.$(date +%s)" 2>/dev/null || true
    else
        log_warn "Orchestrator not running"
    fi
}

cmd_orchestrator_status() {
    if [ -f "$LOGS_DIR/orchestrator/pid" ]; then
        local pid=$(cat "$LOGS_DIR/orchestrator/pid")
        if ps -p "$pid" &>/dev/null; then
            echo -e "Orchestrator: ${GREEN}running${NC} (PID: $pid)"
            echo "  Tasks pending: $(grep -cv '^#\|^$' "$SCRIPT_DIR/tasks.txt" 2>/dev/null || echo 0)"
            return
        fi
    fi
    echo -e "Orchestrator: ${RED}stopped${NC}"
}
