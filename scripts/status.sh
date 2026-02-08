#!/bin/bash
# status.sh - Show status of all components
# Usage: ./scripts/status.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."

# Auto-detect MA_PREFIX from project-config.md if not set
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; GRAY='\033[0;90m'; NC='\033[0m'

ok()   { printf "  ${GREEN}%-12s${NC} %s\n" "✓ $1" "$2"; }
warn() { printf "  ${YELLOW}%-12s${NC} %s\n" "● $1" "$2"; }
fail() { printf "  ${RED}%-12s${NC} %s\n" "✗ $1" "$2"; }

echo ""
echo -e "${BLUE}═══════════════════════════════════════${NC}"
echo -e "${BLUE}   Multi-Agent Status (${MA_PREFIX})${NC}"
echo -e "${BLUE}═══════════════════════════════════════${NC}"
echo ""

# ── Redis ──
echo -e "${BLUE}── Redis ──${NC}"
if redis-cli ping &>/dev/null 2>&1; then
    KEYS=$(redis-cli DBSIZE 2>/dev/null | grep -o '[0-9]*')
    ok "Redis" "PONG ($KEYS keys)"
else
    fail "Redis" "not running"
fi
echo ""

# ── Docker ──
echo -e "${BLUE}── Docker ──${NC}"
if command -v docker &>/dev/null && (docker info &>/dev/null 2>&1 || sudo docker info &>/dev/null 2>&1); then
    DOCKER="docker"
    docker info &>/dev/null 2>&1 || DOCKER="sudo docker"

    if $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -q ma-keycloak; then
        ok "Keycloak" "running"
    else
        fail "Keycloak" "stopped"
    fi

    if $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -q ma-redis; then
        ok "Redis-Docker" "running"
    fi
else
    warn "Docker" "not available"
fi
echo ""

# ── Dashboard ──
echo -e "${BLUE}── Dashboard ──${NC}"
if lsof -i :8000 &>/dev/null 2>&1; then
    PID=$(lsof -ti :8000 2>/dev/null | head -1)
    ok "Dashboard" ":8000 (PID: $PID)"
else
    fail "Dashboard" "not running"
fi

if lsof -i :80 &>/dev/null 2>&1 || sudo lsof -i :80 &>/dev/null 2>&1; then
    PROC=$(sudo lsof -i :80 2>/dev/null | awk 'NR==2{print $1}' || echo "?")
    ok "Port 80" "$PROC"
fi
echo ""

# ── Agents ──
echo -e "${BLUE}── Agents ──${NC}"
SESSIONS=$(tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | cut -d: -f1 || true)

if [ -z "$SESSIONS" ]; then
    fail "Agents" "no sessions found"
else
    TOTAL=0
    BUSY=0
    ARCHITECTS=""
    MASTERS=""
    WORKERS=""

    while IFS= read -r session; do
        ID="${session#${MA_PREFIX}-agent-}"
        TOTAL=$((TOTAL + 1))

        # Check if busy (esc to interrupt)
        STATUS="idle"
        CAPTURE=$(tmux capture-pane -t "${session}.0" -p -S -5 2>/dev/null || true)
        if echo "$CAPTURE" | grep -q "esc to interrupt"; then
            STATUS="busy"
            BUSY=$((BUSY + 1))
        fi

        NUM=${ID#0}  # remove leading zeros for comparison
        NUM=${NUM:-0}
        if [ "$NUM" -ge 900 ] 2>/dev/null; then
            ARCHITECTS="$ARCHITECTS $ID($STATUS)"
        elif [ "$NUM" -lt 100 ] 2>/dev/null; then
            MASTERS="$MASTERS $ID($STATUS)"
        elif [ "$NUM" -lt 200 ] 2>/dev/null; then
            MASTERS="$MASTERS $ID($STATUS)"
        else
            WORKERS="$WORKERS $ID($STATUS)"
        fi
    done <<< "$SESSIONS"

    ok "Total" "$TOTAL agents ($BUSY busy)"

    if [ -n "$ARCHITECTS" ]; then
        echo -e "  ${GRAY}9XX:${NC}$ARCHITECTS"
    fi
    if [ -n "$MASTERS" ]; then
        echo -e "  ${GRAY}0-1XX:${NC}$MASTERS"
    fi
    if [ -n "$WORKERS" ]; then
        # Count by range instead of listing all
        W_COUNT=$(echo "$WORKERS" | wc -w | tr -d ' ')
        W_BUSY=$(echo "$WORKERS" | grep -o "busy" | wc -l | tr -d ' ')
        echo -e "  ${GRAY}2-8XX:${NC} $W_COUNT workers ($W_BUSY busy)"
    fi
fi
echo ""

# ── System ──
echo -e "${BLUE}── System ──${NC}"
ULIMIT=$(ulimit -n 2>/dev/null)
if [ "$ULIMIT" -lt 1024 ] 2>/dev/null; then
    warn "ulimit -n" "$ULIMIT (low — recommend 10240)"
else
    ok "ulimit -n" "$ULIMIT"
fi

LOAD=$(uptime | sed 's/.*load average[s]*: //')
ok "Load" "$LOAD"

echo ""
