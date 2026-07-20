#!/bin/bash
# D3 — démarre un agent de banc dédié avec le réseau du CLI coupé.
set -euo pipefail
BASE="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_ID="${1:-300}"
if ! command -v unshare >/dev/null 2>&1; then
    echo "unshare absent : isolation réseau impossible" >&2
    exit 1
fi
"$BASE/scripts/agent.sh" stop "$AGENT_ID" || true
CLAUDE_WRAPPER="unshare --net --map-root-user" "$BASE/scripts/agent.sh" start "$AGENT_ID"
mkdir -p "$BASE/sessions"
printf '{"agent":"%s","sealed_net":true,"wrapper":"unshare --net --map-root-user"}\n' \
    "$AGENT_ID" > "$BASE/sessions/bench-sealed-agent.json"
echo "Agent $AGENT_ID démarré avec réseau CLI isolé."
