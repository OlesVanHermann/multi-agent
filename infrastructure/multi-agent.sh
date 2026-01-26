#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_ok() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

redis_cmd() {
    local container="ma-redis"
    docker ps 2>/dev/null | grep -q ma-redis-mac && container="ma-redis-mac"
    docker exec "$container" redis-cli "$@" 2>/dev/null
}

# ===========================================
# RW - Read-Write
# ===========================================
cmd_rw() {
    local agent_id=$1; shift; local message="$*"
    [[ -z "$agent_id" ]] && { log_error "Usage: ./multi-agent.sh RW <agent> [message]"; exit 1; }
    
    if [[ -n "$message" ]]; then
        redis_cmd RPUSH "ma:inject:${agent_id}" "$message" > /dev/null
        log_ok "→ $agent_id: $message"
    else
        log_info "RW session: $agent_id (Ctrl+C to exit)"
        (
            redis_cmd SUBSCRIBE "ma:conversation:${agent_id}:live" | while read -r line; do
                [[ "$line" == "{"* ]] && echo "$line" | python3 -c "
import sys,json
d=json.load(sys.stdin)
r,c=d.get('role','?').upper(),d.get('content','')[:800]
colors={'USER':'\033[94m','ASSISTANT':'\033[92m','SYSTEM':'\033[90m'}
print(f\"\r{colors.get(r,'')}[{r}]\033[0m {c}\n\033[93m>\033[0m \",end='',flush=True)
" 2>/dev/null
            done
        ) &
        trap "kill $! 2>/dev/null" EXIT
        while read -rep $'\033[93m>\033[0m ' input; do
            [[ "$input" == "exit" ]] && break
            [[ -n "$input" ]] && redis_cmd RPUSH "ma:inject:${agent_id}" "$input" > /dev/null
        done
    fi
}

# ===========================================
# RO - Read-Only
# ===========================================
cmd_ro() {
    local pattern=$1; shift
    [[ -z "$pattern" ]] && { log_error "Usage: ./multi-agent.sh RO <agent|pattern>"; exit 1; }
    [[ -n "$*" ]] && { log_error "RO is read-only, use RW to send"; exit 1; }
    
    log_info "RO watching: $pattern (Ctrl+C to exit)"
    
    if [[ "$pattern" == *"*"* ]]; then
        redis_cmd PSUBSCRIBE "ma:conversation:${pattern}:live"
    else
        redis_cmd SUBSCRIBE "ma:conversation:${pattern}:live"
    fi 2>/dev/null | while read -r line; do
        [[ "$line" == "{"* ]] && echo "$line" | python3 -c "
import sys,json
d=json.load(sys.stdin)
r,c,t=d.get('role','?').upper(),d.get('content','')[:500],d.get('timestamp','')[:19]
colors={'USER':'\033[94m','ASSISTANT':'\033[92m','SYSTEM':'\033[90m'}
print(f\"{colors.get(r,'')}[{t}] {r}:\033[0m {c[:100]}\")" 2>/dev/null
    done
}

# ===========================================
# Infrastructure
# ===========================================
cmd_start() {
    local mode=${1:-standalone}
    log_info "Starting ($mode)..."
    case $mode in
        standalone) docker compose -f docker-compose.standalone.yml up -d ;;
        full|mac) docker compose -f docker-compose.yml --env-file .env.mac up -d ;;
    esac
    sleep 2
    log_ok "Redis: 127.0.0.1:6379"
    [[ "$mode" != "standalone" ]] && log_ok "Dashboard: http://127.0.0.1:8080"
}

cmd_stop() {
    log_info "Stopping..."
    docker compose -f docker-compose.standalone.yml down 2>/dev/null || true
    docker compose -f docker-compose.yml down 2>/dev/null || true
    log_ok "Stopped"
}

cmd_status() {
    echo -e "${CYAN}=== Infrastructure ===${NC}"
    docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null | grep ma- || echo "  (not running)"
    
    echo -e "\n${CYAN}=== Agents ===${NC}"
    redis_cmd HGETALL "ma:agents" | python3 -c "
import sys,json
lines=sys.stdin.read().strip().split('\n')
if not lines or lines==['']:print('  (none)')
else:
    i=0
    while i<len(lines)-1:
        try:
            d=json.loads(lines[i+1])
            print(f\"  {lines[i]}: {d.get('role','?')} [{d.get('status','?')}] tasks:{d.get('tasks_completed',0)}\")
        except:pass
        i+=2
" 2>/dev/null || echo "  (none)"
    
    echo -e "\n${CYAN}=== Project ===${NC}"
    echo "  Active: $(cat .active_project 2>/dev/null || echo 'none')"
}

# ===========================================
# Agent Commands
# ===========================================
cmd_agent() {
    local role="" agent_id="" project=$(cat .active_project 2>/dev/null || echo "default")
    while [[ $# -gt 0 ]]; do
        case $1 in
            --role) role="$2"; shift 2 ;;
            --id) agent_id="$2"; shift 2 ;;
            --project) project="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    [[ -z "$role" ]] && { log_error "Usage: ./multi-agent.sh agent --role <super-master|master|slave> [--id <id>]"; exit 1; }
    python3 ../core/agent-runner/agent_runner.py --role "$role" --id "${agent_id:-$role}" --project "$project"
}

cmd_list() {
    redis_cmd HGETALL "ma:agents" | python3 -c "
import sys,json
lines=sys.stdin.read().strip().split('\n')
if not lines or lines==['']:print('No agents')
else:
    i=0
    while i<len(lines)-1:
        try:
            d=json.loads(lines[i+1])
            print(f\"{lines[i]}: {d.get('role','?')} [{d.get('status','?')}]\")
        except:pass
        i+=2
" 2>/dev/null
}

cmd_kill() {
    local agent_id=$1
    [[ -z "$agent_id" ]] && { log_error "Usage: ./multi-agent.sh kill <agent_id>"; exit 1; }
    redis_cmd HDEL "ma:agents" "$agent_id" > /dev/null
    redis_cmd DEL "ma:inject:${agent_id}" > /dev/null
    log_ok "Removed: $agent_id (process may still be running, Ctrl+C it)"
}

cmd_clear() {
    local agent_id=$1
    [[ -z "$agent_id" ]] && { log_error "Usage: ./multi-agent.sh clear <agent_id>"; exit 1; }
    redis_cmd DEL "ma:conversation:${agent_id}" > /dev/null
    log_ok "Cleared conversation: $agent_id"
}

cmd_logs() {
    local agent_id=$1 count=${2:-50}
    [[ -z "$agent_id" ]] && { log_error "Usage: ./multi-agent.sh logs <agent_id> [count]"; exit 1; }
    
    redis_cmd XRANGE "ma:conversation:${agent_id}" - + COUNT "$count" | python3 -c "
import sys
lines=sys.stdin.read()
import re
for m in re.finditer(r'role\n(\w+)\ncontent\n(.*?)\ntimestamp\n(\S+)',lines,re.S):
    r,c,t=m.groups()
    c=c.strip()[:200]
    colors={'user':'\033[94m','assistant':'\033[92m','system':'\033[90m'}
    print(f\"{colors.get(r,'')}[{t[:19]}] {r.upper()}:\033[0m {c}\")
" 2>/dev/null
}

# ===========================================
# Stats & Export
# ===========================================
cmd_stats() {
    echo -e "${CYAN}=== Stats ===${NC}"
    
    local agents=$(redis_cmd HLEN "ma:agents" 2>/dev/null || echo 0)
    echo "  Agents: $agents"
    
    local project=$(cat .active_project 2>/dev/null || echo "default")
    local tasks=$(redis_cmd XLEN "ma:tasks:${project}" 2>/dev/null || echo 0)
    echo "  Tasks in queue: $tasks"
    
    local results=$(redis_cmd KEYS "ma:results:*" 2>/dev/null | wc -l)
    echo "  Results stored: $results"
    
    echo ""
    echo -e "${CYAN}=== Per Agent ===${NC}"
    redis_cmd HGETALL "ma:agents" | python3 -c "
import sys,json
lines=sys.stdin.read().strip().split('\n')
i=0
while i<len(lines)-1:
    try:
        d=json.loads(lines[i+1])
        print(f\"  {lines[i]}: {d.get('tasks_completed',0)} tasks completed\")
    except:pass
    i+=2
" 2>/dev/null
}

cmd_export() {
    local project=${1:-$(cat .active_project 2>/dev/null || echo "default")}
    local outdir="projects/${project}/exports"
    mkdir -p "$outdir"
    
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local outfile="${outdir}/export_${timestamp}.json"
    
    log_info "Exporting project: $project"
    
    # Export results
    redis_cmd KEYS "ma:results:*" | while read -r key; do
        redis_cmd GET "$key"
    done | python3 -c "
import sys,json
results=[]
for line in sys.stdin:
    line=line.strip()
    if line:
        try:results.append(json.loads(line))
        except:pass
print(json.dumps({'project':'$project','exported_at':'$(date -Iseconds)','results':results},indent=2))
" > "$outfile"
    
    log_ok "Exported to: $outfile"
}

# ===========================================
# Project & Task
# ===========================================
cmd_new_project() {
    local name=$1
    [[ -z "$name" ]] && { log_error "Usage: ./multi-agent.sh new-project <n>"; exit 1; }
    mkdir -p "projects/$name"/{knowledge,outputs,exports}
    echo "# $name" > "projects/$name/knowledge/context.md"
    echo "$name" > .active_project
    log_ok "Created: $name"
}

cmd_activate() {
    local name=$1
    [[ ! -d "projects/$name" ]] && { log_error "Not found: $name"; exit 1; }
    echo "$name" > .active_project
    log_ok "Activated: $name"
}

cmd_projects() {
    local active=$(cat .active_project 2>/dev/null || echo "")
    for d in projects/*/; do
        [[ -d "$d" ]] || continue
        local name=$(basename "$d")
        [[ "$name" == "$active" ]] && echo -e "  ${GREEN}* $name${NC}" || echo "    $name"
    done
}

cmd_task() {
    local desc="$*"
    [[ -z "$desc" ]] && { log_error "Usage: ./multi-agent.sh task <description>"; exit 1; }
    local project=$(cat .active_project 2>/dev/null || echo "default")
    local task_id="task-$(date +%s)-$$"
    local payload=$(python3 -c "import json;print(json.dumps({'task_id':'$task_id','project':'$project','description':'''$desc'''}))")
    redis_cmd XADD "ma:tasks:$project" "*" "payload" "$payload" > /dev/null
    log_ok "Task: $task_id"
    echo "$task_id"
}

cmd_result() {
    local task_id=$1
    [[ -z "$task_id" ]] && { log_error "Usage: ./multi-agent.sh result <task_id>"; exit 1; }
    redis_cmd GET "ma:results:$task_id" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(f\"Status: {d.get('status')}\nAgent: {d.get('agent_id')}\n\n{d.get('output','')}\")
except:print('No result')
" 2>/dev/null
}

# ===========================================
# Help
# ===========================================
cmd_help() {
    cat << EOF
${CYAN}Multi-Agent${NC} - Multi-agent AI with Claude Code

${YELLOW}Read/Write${NC}
  ./multi-agent.sh RW <agent> [message]     Interactive or send message
  ./multi-agent.sh RO <agent|pattern>       Watch (read-only)

${YELLOW}Agents${NC}
  ./multi-agent.sh agent --role <role> [--id <id>]
  ./multi-agent.sh list                     List agents
  ./multi-agent.sh kill <agent>             Remove agent
  ./multi-agent.sh clear <agent>            Clear conversation
  ./multi-agent.sh logs <agent> [n]         View last n messages

${YELLOW}Infrastructure${NC}
  ./multi-agent.sh start [standalone|mac|vm]
  ./multi-agent.sh stop
  ./multi-agent.sh status

${YELLOW}Projects${NC}
  ./multi-agent.sh new-project <n>
  ./multi-agent.sh activate <n>
  ./multi-agent.sh projects

${YELLOW}Tasks${NC}
  ./multi-agent.sh task <description>
  ./multi-agent.sh result <task_id>

${YELLOW}Stats & Export${NC}
  ./multi-agent.sh stats                    Global statistics
  ./multi-agent.sh export [project]         Export results to JSON

${YELLOW}Dashboard${NC}
  http://127.0.0.1:8080

${YELLOW}Examples${NC}
  ./multi-agent.sh start                    # Start Redis + Dashboard
  ./multi-agent.sh agent --role master      # Terminal 1
  ./multi-agent.sh agent --role slave --id slave-01  # Terminal 2
  ./multi-agent.sh RO master                # Watch master
  ./multi-agent.sh RW master "do X"         # Send command
  ./multi-agent.sh logs slave-01 100        # View logs
  ./multi-agent.sh stats                    # See stats
EOF
}

# ===========================================
# Main
# ===========================================
case "${1:-help}" in
    RW|rw) shift; cmd_rw "$@" ;;
    RO|ro) shift; cmd_ro "$@" ;;
    start) cmd_start "$2" ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    agent) shift; cmd_agent "$@" ;;
    list) cmd_list ;;
    kill) cmd_kill "$2" ;;
    clear) cmd_clear "$2" ;;
    logs) cmd_logs "$2" "$3" ;;
    stats) cmd_stats ;;
    export) cmd_export "$2" ;;
    new-project) cmd_new_project "$2" ;;
    activate) cmd_activate "$2" ;;
    projects) cmd_projects ;;
    task) shift; cmd_task "$@" ;;
    result) cmd_result "$2" ;;
    help|--help|-h) cmd_help ;;
    *) log_error "Unknown: $1"; cmd_help; exit 1 ;;
esac
