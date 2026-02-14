#!/bin/bash
# proxy.sh - Reverse proxy 0.0.0.0:80 → 127.0.0.1:8000
# Usage: ./scripts/proxy.sh start   # Start proxy (needs sudo on Linux for port 80)
#        ./scripts/proxy.sh stop    # Stop proxy

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
LOG_DIR="$BASE_DIR/logs/000"
PID_FILE="$LOG_DIR/proxy.pid"

LISTEN_HOST="0.0.0.0"
LISTEN_PORT=80
BACKEND_HOST="127.0.0.1"
BACKEND_PORT=8000

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

do_start() {
    mkdir -p "$LOG_DIR"

    # Check if already running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_warn "Proxy already running (PID: $PID)"
            return
        fi
    fi

    # Check if port is already in use
    if lsof -i :$LISTEN_PORT &>/dev/null 2>&1 || sudo lsof -i :$LISTEN_PORT &>/dev/null 2>&1; then
        log_error "Port $LISTEN_PORT already in use:"
        sudo lsof -i :$LISTEN_PORT 2>/dev/null | head -3
        exit 1
    fi

    # Check backend is reachable
    if ! curl -s -o /dev/null --max-time 2 "http://$BACKEND_HOST:$BACKEND_PORT" 2>/dev/null; then
        log_warn "Backend http://$BACKEND_HOST:$BACKEND_PORT not reachable — proxy will start anyway"
    fi

    log_info "Starting proxy $LISTEN_HOST:$LISTEN_PORT → $BACKEND_HOST:$BACKEND_PORT..."

    # Write proxy script to a temp file (avoids quoting issues)
    # TCP-level proxy: forwards raw bytes bidirectionally
    # Supports HTTP, WebSocket, and any protocol transparently
    PROXY_PY="$LOG_DIR/.proxy.py"
    cat > "$PROXY_PY" << 'PYEOF'
import socket, threading, sys, signal, selectors

BACKEND = (sys.argv[1], int(sys.argv[2]))
LISTEN  = (sys.argv[3], int(sys.argv[4]))

signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

def pipe(src, dst):
    """Forward data from src to dst until EOF."""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try: dst.shutdown(socket.SHUT_WR)
        except Exception: pass

def handle(client, addr):
    """Handle one client connection: connect to backend, pipe both ways."""
    try:
        backend = socket.create_connection(BACKEND, timeout=10)
        backend.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        t1 = threading.Thread(target=pipe, args=(client, backend), daemon=True)
        t2 = threading.Thread(target=pipe, args=(backend, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        pass
    finally:
        try: client.close()
        except Exception: pass
        try: backend.close()
        except Exception: pass

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(LISTEN)
server.listen(128)
print(f"TCP proxy {LISTEN[0]}:{LISTEN[1]} -> {BACKEND[0]}:{BACKEND[1]}", flush=True)

while True:
    client, addr = server.accept()
    threading.Thread(target=handle, args=(client, addr), daemon=True).start()
PYEOF

    if [ "$LISTEN_PORT" -lt 1024 ] && [ "$(uname)" = "Linux" ]; then
        sudo nohup python3 "$PROXY_PY" "$BACKEND_HOST" "$BACKEND_PORT" "$LISTEN_HOST" "$LISTEN_PORT" \
            >> "$LOG_DIR/proxy.log" 2>&1 &
        sleep 1
        # Find the actual python3 PID (sudo forks)
        PROXY_PID=$(sudo lsof -ti :$LISTEN_PORT 2>/dev/null | head -1)
    else
        nohup python3 "$PROXY_PY" "$BACKEND_HOST" "$BACKEND_PORT" "$LISTEN_HOST" "$LISTEN_PORT" \
            >> "$LOG_DIR/proxy.log" 2>&1 &
        PROXY_PID=$!
        sleep 1
    fi

    if [ -n "$PROXY_PID" ] && (kill -0 "$PROXY_PID" 2>/dev/null || sudo kill -0 "$PROXY_PID" 2>/dev/null); then
        echo "$PROXY_PID" > "$PID_FILE"
        log_ok "Proxy running on http://$LISTEN_HOST:$LISTEN_PORT (PID: $PROXY_PID)"
    else
        log_error "Proxy failed to start. Check $LOG_DIR/proxy.log"
        exit 1
    fi
}

do_stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if sudo kill "$PID" 2>/dev/null || kill "$PID" 2>/dev/null; then
            log_ok "Proxy stopped (PID: $PID)"
        else
            log_warn "Proxy not running (PID: $PID)"
        fi
        mv "$PID_FILE" "$PID_FILE.old" 2>/dev/null || true
    else
        log_warn "No PID file found"
    fi
}

show_help() {
    echo "Usage: $0 <start|stop>"
    echo ""
    echo "  Reverse proxy $LISTEN_HOST:$LISTEN_PORT → $BACKEND_HOST:$BACKEND_PORT"
    echo ""
    echo "  $0 start   Start the proxy"
    echo "  $0 stop    Stop the proxy"
}

case "$1" in
    start)  do_start ;;
    stop)   do_stop ;;
    -h|--help|help|"") show_help ;;
    *)      log_error "Unknown action: $1"; show_help; exit 1 ;;
esac
