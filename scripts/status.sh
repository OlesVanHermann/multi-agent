#!/bin/bash
# status.sh - Show status of all components
# Usage: ./scripts/status.sh          # Quick overview
#        ./scripts/status.sh all      # Full diagnostic (API, auth, WS, logs)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
LOG_DIR="$BASE_DIR/logs"

# Auto-detect MA_PREFIX from project-config.md if not set
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"

# Dashboard URL
DASH_URL="http://127.0.0.1:8000"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; GRAY='\033[0;90m'; CYAN='\033[0;36m'; NC='\033[0m'

ok()   { printf "  ${GREEN}%-14s${NC} %s\n" "✓ $1" "$2"; }
warn() { printf "  ${YELLOW}%-14s${NC} %s\n" "● $1" "$2"; }
fail() { printf "  ${RED}%-14s${NC} %s\n" "✗ $1" "$2"; }
info() { printf "  ${GRAY}%-14s${NC} %s\n" "  $1" "$2"; }

header() {
    echo ""
    echo -e "${BLUE}── $1 ──${NC}"
}

# ══════════════════════════════════════════════════════
# Quick status (default)
# ══════════════════════════════════════════════════════

do_quick() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
    echo -e "${BLUE}   Multi-Agent Status (${MA_PREFIX})${NC}"
    echo -e "${BLUE}═══════════════════════════════════════${NC}"

    header "Redis"
    if redis-cli ping &>/dev/null 2>&1; then
        KEYS=$(redis-cli DBSIZE 2>/dev/null | grep -o '[0-9]*')
        ok "Redis" "PONG ($KEYS keys)"
    else
        fail "Redis" "not running"
    fi

    header "Docker"
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

    header "Dashboard"
    if lsof -iTCP:8000 -sTCP:LISTEN &>/dev/null 2>&1; then
        PID=$(lsof -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | head -1)
        ok "Dashboard" ":8000 (PID: $PID)"
    else
        fail "Dashboard" "not running"
    fi
    if lsof -i :80 &>/dev/null 2>&1 || sudo lsof -i :80 &>/dev/null 2>&1; then
        PROC=$(sudo lsof -i :80 2>/dev/null | awk 'NR==2{print $1}' || echo "?")
        ok "Port 80" "$PROC"
    fi

    header "Agents"
    SESSIONS=$(tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | cut -d: -f1 || true)
    if [ -z "$SESSIONS" ]; then
        fail "Agents" "no sessions found"
    else
        TOTAL=0; BUSY=0
        ARCHITECTS=""; MASTERS=""; WORKERS=""
        while IFS= read -r session; do
            ID="${session#${MA_PREFIX}-agent-}"
            TOTAL=$((TOTAL + 1))
            STATUS="idle"
            CAPTURE=$(tmux capture-pane -t "${session}:0.0" -p -S -5 2>/dev/null || true)
            if echo "$CAPTURE" | grep -q "esc to interrupt"; then
                STATUS="busy"; BUSY=$((BUSY + 1))
            fi
            NUM=${ID#0}; NUM=${NUM:-0}
            if [ "$NUM" -ge 900 ] 2>/dev/null; then
                ARCHITECTS="$ARCHITECTS $ID($STATUS)"
            elif [ "$NUM" -lt 200 ] 2>/dev/null; then
                MASTERS="$MASTERS $ID($STATUS)"
            else
                WORKERS="$WORKERS $ID($STATUS)"
            fi
        done <<< "$SESSIONS"
        ok "Total" "$TOTAL agents ($BUSY busy)"
        [ -n "$ARCHITECTS" ] && echo -e "  ${GRAY}9XX:${NC}$ARCHITECTS"
        [ -n "$MASTERS" ] && echo -e "  ${GRAY}0-1XX:${NC}$MASTERS"
        if [ -n "$WORKERS" ]; then
            W_COUNT=$(echo "$WORKERS" | wc -w | tr -d ' ')
            W_BUSY=$(echo "$WORKERS" | grep -o "busy" | wc -l | tr -d ' ')
            echo -e "  ${GRAY}2-8XX:${NC} $W_COUNT workers ($W_BUSY busy)"
        fi
    fi

    header "System"
    ULIMIT=$(ulimit -n 2>/dev/null)
    if [ "$ULIMIT" -lt 1024 ] 2>/dev/null; then
        warn "ulimit -n" "$ULIMIT (low — recommend 10240)"
    else
        ok "ulimit -n" "$ULIMIT"
    fi
    LOAD=$(uptime | sed 's/.*load average[s]*: //')
    ok "Load" "$LOAD"
    echo ""
}


# ══════════════════════════════════════════════════════
# Full diagnostic (status.sh all)
# ══════════════════════════════════════════════════════

do_full() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}   Multi-Agent FULL Diagnostic (${MA_PREFIX})${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"

    ERRORS=0
    WARNINGS=0

    # ── 1. Redis ──
    header "1. Redis"
    if redis-cli ping &>/dev/null 2>&1; then
        KEYS=$(redis-cli DBSIZE 2>/dev/null | grep -o '[0-9]*')
        ok "ping" "PONG ($KEYS keys)"

        # Check MA_PREFIX keys
        MA_KEYS=$(redis-cli KEYS "${MA_PREFIX}:*" 2>/dev/null | wc -l | tr -d ' ')
        ok "keys" "$MA_KEYS keys with prefix ${MA_PREFIX}:"

        # Check agent status hashes
        AGENT_HASHES=$(redis-cli KEYS "${MA_PREFIX}:agent:*" 2>/dev/null | grep -cE "^${MA_PREFIX}:agent:[0-9]+$" 2>/dev/null || true)
        info "hashes" "${AGENT_HASHES:-0} agent status hashes"
    else
        fail "ping" "NOT RUNNING"
        ERRORS=$((ERRORS + 1))
    fi

    # ── 2. Dashboard backend ──
    header "2. Backend API"
    if ! lsof -iTCP:8000 -sTCP:LISTEN &>/dev/null 2>&1; then
        fail "uvicorn" "not running on :8000"
        ERRORS=$((ERRORS + 1))
    else
        PIDS=$(lsof -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | sort -u)
        PID_COUNT=$(echo "$PIDS" | wc -l | tr -d ' ')
        PID=$(echo "$PIDS" | head -1)
        if [ "$PID_COUNT" -gt 1 ]; then
            warn "uvicorn" "$PID_COUNT processes on :8000!"
            for p in $PIDS; do
                CWD=$(readlink /proc/$p/cwd 2>/dev/null || echo "?")
                info "" "PID $p → $CWD"
            done
            WARNINGS=$((WARNINGS + 1))
        else
            CWD=$(readlink /proc/$PID/cwd 2>/dev/null || echo "?")
            ok "uvicorn" "PID $PID ($CWD)"
        fi

        # GET /api/health
        HEALTH=$(curl -s --max-time 5 "$DASH_URL/api/health" 2>/dev/null)
        if [ -n "$HEALTH" ]; then
            REDIS_OK=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('redis','?'))" 2>/dev/null)
            STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null)
            if [ "$STATUS" = "ok" ]; then
                ok "/api/health" "status=$STATUS redis=$REDIS_OK"
            else
                warn "/api/health" "status=$STATUS redis=$REDIS_OK"
                WARNINGS=$((WARNINGS + 1))
            fi
        else
            fail "/api/health" "no response"
            ERRORS=$((ERRORS + 1))
        fi

        # GET /api/agents
        AGENTS_JSON=$(curl -s --max-time 5 "$DASH_URL/api/agents" 2>/dev/null)
        if [ -n "$AGENTS_JSON" ]; then
            COUNT=$(echo "$AGENTS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null)
            ok "/api/agents" "$COUNT agents found"
        else
            fail "/api/agents" "no response"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    # ── 3. Frontend ──
    header "3. Frontend"
    DIST_DIR="$BASE_DIR/web/frontend/dist"
    if [ -f "$DIST_DIR/index.html" ]; then
        ASSET_COUNT=$(find "$DIST_DIR/assets" -type f 2>/dev/null | wc -l | tr -d ' ')
        DIST_AGE=$(( ($(date +%s) - $(stat -c %Y "$DIST_DIR/index.html" 2>/dev/null || stat -f %m "$DIST_DIR/index.html" 2>/dev/null)) / 60 ))
        ok "build" "$ASSET_COUNT assets (built ${DIST_AGE}min ago)"
    else
        fail "build" "dist/index.html missing — run: ./scripts/web.sh rebuild"
        ERRORS=$((ERRORS + 1))
    fi

    # Fetch index.html from server
    INDEX_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$DASH_URL/" 2>/dev/null)
    if [ "$INDEX_STATUS" = "200" ]; then
        ok "GET /" "HTTP $INDEX_STATUS"
    else
        fail "GET /" "HTTP $INDEX_STATUS"
        ERRORS=$((ERRORS + 1))
    fi

    # Check JS/CSS load (from served HTML, not local disk)
    SERVED_HTML=$(curl -s --max-time 5 "$DASH_URL/" 2>/dev/null)
    if [ -n "$SERVED_HTML" ]; then
        JS_FILE=$(echo "$SERVED_HTML" | grep -o 'assets/index-[^"]*\.js' | head -1)
        if [ -n "$JS_FILE" ]; then
            JS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$DASH_URL/$JS_FILE" 2>/dev/null)
            if [ "$JS_STATUS" = "200" ]; then
                ok "JS" "$JS_FILE → $JS_STATUS"
            else
                fail "JS" "$JS_FILE → $JS_STATUS"
                ERRORS=$((ERRORS + 1))
            fi
        fi
        CSS_FILE=$(echo "$SERVED_HTML" | grep -o 'assets/index-[^"]*\.css' | head -1)
        if [ -n "$CSS_FILE" ]; then
            CSS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$DASH_URL/$CSS_FILE" 2>/dev/null)
            if [ "$CSS_STATUS" = "200" ]; then
                ok "CSS" "$CSS_FILE → $CSS_STATUS"
            else
                fail "CSS" "$CSS_FILE → $CSS_STATUS"
                ERRORS=$((ERRORS + 1))
            fi
        fi
    else
        warn "HTML" "no response from $DASH_URL/"
    fi

    # ── 4. Auth ──
    header "4. Authentication"

    # Try Keycloak
    KC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:8080/health/ready" 2>/dev/null)
    if [ "$KC_STATUS" = "200" ]; then
        ok "Keycloak" "healthy"

        # Try login via Keycloak
        TOKEN_RESP=$(curl -s --max-time 5 \
            -d "grant_type=password&client_id=multi-agent-web&username=octave&password=changeme" \
            "$DASH_URL/auth/realms/multi-agent/protocol/openid-connect/token" 2>/dev/null)
        if echo "$TOKEN_RESP" | grep -q "access_token"; then
            ok "login KC" "octave/changeme → token OK"
        else
            ERR=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error_description','?'))" 2>/dev/null)
            warn "login KC" "failed: $ERR"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        warn "Keycloak" "not reachable (HTTP $KC_STATUS)"

        # Try SIMPLE_AUTH fallback
        TOKEN_RESP=$(curl -s --max-time 5 \
            -d "grant_type=password&client_id=multi-agent-web&username=octave&password=changeme" \
            "$DASH_URL/auth/realms/multi-agent/protocol/openid-connect/token" 2>/dev/null)
        if echo "$TOKEN_RESP" | grep -q "access_token"; then
            ok "login" "SIMPLE_AUTH fallback → token OK"
        elif echo "$TOKEN_RESP" | grep -q "invalid_grant"; then
            fail "login" "Keycloak down + no SIMPLE_AUTH configured"
            info "" "Fix: SIMPLE_AUTH=\"octave:changeme:admin\" in web.sh"
            ERRORS=$((ERRORS + 1))
        else
            fail "login" "no response from auth endpoint"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    # ── 5. WebSocket ──
    header "5. WebSocket"

    # Get first agent ID
    FIRST_AGENT=$(tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | head -1 | sed "s/${MA_PREFIX}-agent-//" | cut -d: -f1)

    if [ -n "$FIRST_AGENT" ]; then
        # Test WebSocket with python3
        WS_RESULT=$(python3 -c "
import asyncio, sys
try:
    import websockets
except ImportError:
    print('NO_LIB')
    sys.exit(0)

async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8000/ws/agent/$FIRST_AGENT', close_timeout=3) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            import json
            data = json.loads(msg)
            print(f'OK:{data.get(\"type\",\"?\")}: {len(data.get(\"output\",\"\"))} chars')
    except asyncio.TimeoutError:
        print('TIMEOUT: connected but no data in 5s')
    except Exception as e:
        print(f'FAIL:{e}')

asyncio.run(test())
" 2>/dev/null)

        case "$WS_RESULT" in
            OK:*)
                ok "WS agent" "agent $FIRST_AGENT → ${WS_RESULT#OK:}"
                ;;
            TIMEOUT*)
                warn "WS agent" "agent $FIRST_AGENT → $WS_RESULT"
                WARNINGS=$((WARNINGS + 1))
                ;;
            NO_LIB)
                warn "WS agent" "python3 websockets not installed (skip)"
                ;;
            *)
                fail "WS agent" "agent $FIRST_AGENT → $WS_RESULT"
                ERRORS=$((ERRORS + 1))
                ;;
        esac

        # Test REST output (compare)
        REST_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$DASH_URL/api/agent/$FIRST_AGENT/output" 2>/dev/null)
        if [ "$REST_STATUS" = "200" ]; then
            REST_LEN=$(curl -s --max-time 5 "$DASH_URL/api/agent/$FIRST_AGENT/output" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('output','')))" 2>/dev/null)
            ok "REST agent" "agent $FIRST_AGENT → $REST_LEN chars (HTTP $REST_STATUS)"
        else
            fail "REST agent" "agent $FIRST_AGENT → HTTP $REST_STATUS"
            ERRORS=$((ERRORS + 1))
        fi
    else
        warn "WS test" "no agent sessions found, skipping"
    fi

    # Test status WebSocket
    WS_STATUS_RESULT=$(python3 -c "
import asyncio, sys
try:
    import websockets
except ImportError:
    print('NO_LIB')
    sys.exit(0)

async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8000/ws/status', close_timeout=3) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=20)
            import json
            data = json.loads(msg)
            count = len(data.get('agents', []))
            print(f'OK:{count} agents')
    except asyncio.TimeoutError:
        print('TIMEOUT: no status in 20s')
    except Exception as e:
        print(f'FAIL:{e}')

asyncio.run(test())
" 2>/dev/null)

    case "$WS_STATUS_RESULT" in
        OK:*)
            ok "WS status" "${WS_STATUS_RESULT#OK:}"
            ;;
        NO_LIB)
            info "WS status" "skipped (no websockets lib)"
            ;;
        *)
            fail "WS status" "$WS_STATUS_RESULT"
            ERRORS=$((ERRORS + 1))
            ;;
    esac

    # ── 6. Reverse Proxy ──
    header "6. Reverse Proxy"

    # Detect what's in front of :8000
    for PORT in 443 80; do
        if lsof -i :$PORT &>/dev/null 2>&1 || sudo lsof -i :$PORT &>/dev/null 2>&1; then
            PROC=$(sudo lsof -i :$PORT 2>/dev/null | awk 'NR==2{print $1}' || echo "?")
            PROTO="http"; [ "$PORT" = "443" ] && PROTO="https"
            PROXY_URL="${PROTO}://127.0.0.1:${PORT}"

            # Test HTTP through proxy
            PROXY_STATUS=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "$PROXY_URL/api/health" 2>/dev/null)
            if [ "$PROXY_STATUS" = "200" ]; then
                ok ":$PORT ($PROC)" "HTTP → :8000 OK"
            else
                warn ":$PORT ($PROC)" "HTTP → $PROXY_STATUS (may not proxy to :8000)"
                WARNINGS=$((WARNINGS + 1))
            fi

            # Test WS through proxy
            if [ -n "$FIRST_AGENT" ]; then
                WS_PROTO="ws"; [ "$PORT" = "443" ] && WS_PROTO="wss"
                WS_PROXY=$(python3 -c "
import asyncio, ssl, sys
try:
    import websockets
except ImportError:
    print('NO_LIB'); sys.exit(0)
async def test():
    try:
        kw = {}
        if '$WS_PROTO' == 'wss':
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kw['ssl'] = ctx
        async with websockets.connect('${WS_PROTO}://127.0.0.1:${PORT}/ws/agent/$FIRST_AGENT', close_timeout=3, **kw) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print('OK')
    except asyncio.TimeoutError:
        print('TIMEOUT')
    except Exception as e:
        print(f'FAIL:{e}')
asyncio.run(test())
" 2>/dev/null)
                case "$WS_PROXY" in
                    OK) ok "WS :$PORT" "→ WebSocket works" ;;
                    NO_LIB) info "WS :$PORT" "skipped (no websockets lib)" ;;
                    TIMEOUT) warn "WS :$PORT" "connected but no data in 5s"; WARNINGS=$((WARNINGS + 1)) ;;
                    *) fail "WS :$PORT" "$WS_PROXY"; ERRORS=$((ERRORS + 1)) ;;
                esac
            fi
        fi
    done

    # Check if nothing on 80/443
    if ! (lsof -i :80 &>/dev/null 2>&1 || sudo lsof -i :80 &>/dev/null 2>&1 || \
          lsof -i :443 &>/dev/null 2>&1 || sudo lsof -i :443 &>/dev/null 2>&1); then
        info "proxy" "no proxy on :80 or :443 (direct access to :8000 only)"
    fi

    # ── 7. Tmux agents ──
    header "7. Agent Sessions"
    SESSIONS=$(tmux ls 2>/dev/null | grep "^${MA_PREFIX}-agent-" | cut -d: -f1 || true)
    if [ -z "$SESSIONS" ]; then
        fail "tmux" "no ${MA_PREFIX}-agent-* sessions"
        ERRORS=$((ERRORS + 1))
    else
        TOTAL=0; OK_AGENTS=0; FAIL_AGENTS=""
        while IFS= read -r session; do
            ID="${session#${MA_PREFIX}-agent-}"
            TOTAL=$((TOTAL + 1))

            # Check capture-pane works
            CAPTURE=$(tmux capture-pane -t "${session}:0.0" -p -S -3 2>&1)
            if [ $? -eq 0 ]; then
                OK_AGENTS=$((OK_AGENTS + 1))
            else
                FAIL_AGENTS="$FAIL_AGENTS $ID"
            fi

            # Check bridge window exists
            BRIDGE=$(tmux list-windows -t "$session" -F '#{window_name}' 2>/dev/null | grep -c bridge)
            if [ "$BRIDGE" -eq 0 ]; then
                FAIL_AGENTS="$FAIL_AGENTS ${ID}(no-bridge)"
            fi
        done <<< "$SESSIONS"

        ok "sessions" "$TOTAL total, $OK_AGENTS capture OK"
        if [ -n "$FAIL_AGENTS" ]; then
            fail "broken" "$FAIL_AGENTS"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    # ── 8. Logs ──
    header "8. Logs"

    # Dashboard log
    DASH_LOG="$LOG_DIR/000/dashboard.log"
    if [ -f "$DASH_LOG" ]; then
        DASH_SIZE=$(wc -l < "$DASH_LOG" | tr -d ' ')
        DASH_ERRORS=$(grep -ci "error\|traceback\|exception" "$DASH_LOG" 2>/dev/null || true)
        DASH_ERRORS=${DASH_ERRORS:-0}
        DASH_LAST=$(tail -1 "$DASH_LOG" 2>/dev/null | head -c 100)
        if [ "$DASH_ERRORS" -gt 0 ]; then
            warn "dashboard" "$DASH_SIZE lines, $DASH_ERRORS errors"
            # Show last 3 unique errors
            grep -i "error\|traceback" "$DASH_LOG" 2>/dev/null | tail -5 | while read -r line; do
                info "" "$(echo "$line" | head -c 120)"
            done
        else
            ok "dashboard" "$DASH_SIZE lines, 0 errors"
        fi
    else
        info "dashboard" "no log file"
    fi

    # Bridge logs
    BRIDGE_ERRORS=0
    BRIDGE_LOGS=0
    for logfile in "$LOG_DIR"/*/bridge.log; do
        [ -f "$logfile" ] || continue
        BRIDGE_LOGS=$((BRIDGE_LOGS + 1))
        ERRS=$(grep -ci "error\|traceback\|exception" "$logfile" 2>/dev/null || true)
        BRIDGE_ERRORS=$((BRIDGE_ERRORS + ${ERRS:-0}))
    done
    if [ "$BRIDGE_LOGS" -gt 0 ]; then
        if [ "$BRIDGE_ERRORS" -gt 0 ]; then
            warn "bridges" "$BRIDGE_LOGS log files, $BRIDGE_ERRORS total errors"
            # Show which bridges have errors
            for logfile in "$LOG_DIR"/*/bridge.log; do
                [ -f "$logfile" ] || continue
                ERRS=$(grep -ci "error\|traceback\|exception" "$logfile" 2>/dev/null || true)
                [ "${ERRS:-0}" -gt 0 ] 2>/dev/null && info "" "$(basename $(dirname $logfile))/bridge.log: $ERRS errors"
            done
        else
            ok "bridges" "$BRIDGE_LOGS log files, 0 errors"
        fi
    else
        info "bridges" "no bridge logs"
    fi

    # Proxy log
    PROXY_LOG="$LOG_DIR/000/proxy.log"
    if [ -f "$PROXY_LOG" ]; then
        PROXY_SIZE=$(wc -l < "$PROXY_LOG" | tr -d ' ')
        PROXY_ERRORS=$(grep -ci "error\|traceback\|exception" "$PROXY_LOG" 2>/dev/null || true)
        PROXY_ERRORS=${PROXY_ERRORS:-0}
        if [ "$PROXY_ERRORS" -gt 0 ]; then
            warn "proxy" "$PROXY_SIZE lines, $PROXY_ERRORS errors"
        else
            ok "proxy" "$PROXY_SIZE lines, 0 errors"
        fi
    fi

    # ── 9. System ──
    header "9. System"
    ULIMIT=$(ulimit -n 2>/dev/null)
    if [ "$ULIMIT" -lt 1024 ] 2>/dev/null; then
        warn "ulimit -n" "$ULIMIT (low — recommend 10240)"
        WARNINGS=$((WARNINGS + 1))
    else
        ok "ulimit -n" "$ULIMIT"
    fi
    LOAD=$(uptime | sed 's/.*load average[s]*: //')
    ok "Load" "$LOAD"

    PYTHON_VER=$(python3 --version 2>/dev/null | awk '{print $2}')
    ok "Python" "$PYTHON_VER"

    TMUX_VER=$(tmux -V 2>/dev/null)
    ok "tmux" "$TMUX_VER"

    # ── Summary ──
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    if [ "$ERRORS" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
        echo -e "${GREEN}   ALL OK${NC}"
    elif [ "$ERRORS" -eq 0 ]; then
        echo -e "${YELLOW}   $WARNINGS warning(s)${NC}"
    else
        echo -e "${RED}   $ERRORS error(s), $WARNINGS warning(s)${NC}"
    fi
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo ""
}


# ── Main ──

case "${1:-}" in
    all)    do_full ;;
    -h|--help|help)
        echo "Usage: $0 [all]"
        echo ""
        echo "  $0          Quick overview (Redis, Docker, Dashboard, Agents)"
        echo "  $0 all      Full diagnostic (API, auth, WebSocket, logs, proxy)"
        ;;
    *)      do_quick ;;
esac
