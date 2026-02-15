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
    # Asyncio TCP proxy: single-threaded, non-blocking, handles thousands of connections
    # Supports HTTP, WebSocket, and any protocol transparently
    PROXY_PY="$LOG_DIR/.proxy.py"
    cat > "$PROXY_PY" << 'PYEOF'
import asyncio, sys, signal

BACKEND_HOST, BACKEND_PORT = sys.argv[1], int(sys.argv[2])
LISTEN_HOST, LISTEN_PORT = sys.argv[3], int(sys.argv[4])

async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle(client_reader, client_writer):
    try:
        backend_reader, backend_writer = await asyncio.wait_for(
            asyncio.open_connection(BACKEND_HOST, BACKEND_PORT), timeout=10
        )
        backend_writer.transport.set_write_buffer_limits(high=262144)
        client_writer.transport.set_write_buffer_limits(high=262144)
    except Exception:
        client_writer.close()
        return
    await asyncio.gather(
        pipe(client_reader, backend_writer),
        pipe(backend_reader, client_writer),
    )

async def main():
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT, backlog=256)
    print(f"TCP proxy {LISTEN_HOST}:{LISTEN_PORT} -> {BACKEND_HOST}:{BACKEND_PORT}", flush=True)
    async with server:
        await server.serve_forever()

loop = asyncio.new_event_loop()
loop.add_signal_handler(signal.SIGTERM, loop.stop)
loop.run_until_complete(main())
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
