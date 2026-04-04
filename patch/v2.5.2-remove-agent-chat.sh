#!/bin/bash
# v2.5.2-remove-agent-chat.sh — Remove AgentChat (Robeke shim) from dashboard
# Idempotent: safe to run multiple times
#
# Usage: cd ~/multi-agent && bash patch/v2.5.2-remove-agent-chat.sh

set -e
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_skip() { echo -e "[SKIP] $1"; }

APP="$BASE/web/frontend/src/App.jsx"
CSS="$BASE/web/frontend/src/index.css"
SRV="$BASE/web/backend/server.py"
CHAT="$BASE/web/frontend/src/components/AgentChat.jsx"

echo "=== Remove AgentChat (Robeke shim) ==="
echo ""

# 1. Remove AgentChat.jsx
if [ -f "$CHAT" ]; then
    mkdir -p "$BASE/removed"
    mv "$CHAT" "$BASE/removed/$(date +%Y%m%d_%H%M%S)_AgentChat.jsx"
    log_ok "AgentChat.jsx moved to removed/"
else
    log_skip "AgentChat.jsx already absent"
fi

# 2. App.jsx: remove import + usage
if grep -q "AgentChat" "$APP" 2>/dev/null; then
    sed -i '/import AgentChat/d' "$APP"
    sed -i '/<AgentChat/d' "$APP"
    log_ok "App.jsx cleaned"
else
    log_skip "App.jsx already clean"
fi

# 3. index.css: remove agent-chat styles
if grep -q "agent-chat" "$CSS" 2>/dev/null; then
    sed -i '/\/\* === Agent Chat/,/cursor: not-allowed;/{/cursor: not-allowed;/{N;d;};d;}' "$CSS"
    sed -i '/\.agent-chat/d' "$CSS"
    log_ok "index.css cleaned"
else
    log_skip "index.css already clean"
fi

# 4. server.py: remove shim proxy routes
if grep -q "agent-chat" "$SRV" 2>/dev/null; then
    sed -i '/# === Agent Shim Proxy/,/Agent shim unreachable")/d' "$SRV"
    log_ok "server.py cleaned"
else
    log_skip "server.py already clean"
fi

echo ""
echo "Done. Rebuild frontend and restart backend to apply."
