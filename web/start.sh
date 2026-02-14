#!/bin/bash
# Multi-Agent Dashboard - Quick Start
# Usage: ./start.sh [dev|prod]
#   dev  = Vite dev server (hot reload) + backend
#   prod = Build frontend + serve via backend (default)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-prod}"

echo "=== Multi-Agent Dashboard ==="
echo "Mode: $MODE"
echo ""

# Check Python dependencies
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "[backend] Installing Python dependencies..."
    pip3 install -r "$SCRIPT_DIR/backend/requirements.txt"
fi

if [ "$MODE" = "dev" ]; then
    # Dev mode: Vite dev server + backend
    echo "[frontend] Installing npm dependencies..."
    cd "$SCRIPT_DIR/frontend"
    npm install

    echo ""
    echo "[frontend] Starting Vite dev server on :3000..."
    npm run dev &
    VITE_PID=$!

    echo "[backend] Starting FastAPI on :8000..."
    cd "$SCRIPT_DIR/backend"
    MA_PREFIX="${MA_PREFIX:-ma}" python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload &
    BACKEND_PID=$!

    echo ""
    echo "Dashboard: http://localhost:3000"
    echo "API:       http://localhost:8000"
    echo ""
    echo "Press Ctrl+C to stop"

    trap "kill $VITE_PID $BACKEND_PID 2>/dev/null; exit" INT TERM
    wait
else
    # Prod mode: build frontend then serve via backend
    cd "$SCRIPT_DIR/frontend"

    if [ ! -d "node_modules" ]; then
        echo "[frontend] Installing npm dependencies..."
        npm install
    fi

    echo "[frontend] Building..."
    npm run build

    echo "[backend] Starting FastAPI on :8000..."
    cd "$SCRIPT_DIR/backend"
    MA_PREFIX="${MA_PREFIX:-ma}" python3 -m uvicorn server:app --host 127.0.0.1 --port 8000

    # Backend serves frontend from ../frontend/dist
fi
