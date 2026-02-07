#!/bin/bash
# watch.sh - Écoute les réponses d'un agent via Redis Streams
# Usage: ./watch.sh <agent_id>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Auto-detect MA_PREFIX from project-config.md if not set
if [ -z "${MA_PREFIX:-}" ] && [ -f "$BASE_DIR/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$BASE_DIR/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"

AGENT_ID=${1:-300}
STREAM="${MA_PREFIX}:agent:${AGENT_ID}:outbox"

echo "Watching agent $AGENT_ID responses..."
echo "Stream: $STREAM"
echo "Press Ctrl+C to quit"
echo "---"

# Commencer après le dernier message existant
LAST_ID=$(redis-cli XINFO STREAM "$STREAM" 2>/dev/null | grep -A1 "last-generated-id" | tail -1 || echo "0-0")
if [ -z "$LAST_ID" ] || [ "$LAST_ID" = "0-0" ]; then
    LAST_ID='$'
fi

while true; do
    # Lire UN message à la fois, bloquer 5 secondes max
    RESULT=$(redis-cli XREAD BLOCK 5000 COUNT 1 STREAMS "$STREAM" "$LAST_ID" 2>/dev/null)

    if [ -n "$RESULT" ]; then
        # Extraire l'ID du message (format: 1234567890123-0)
        NEW_ID=$(echo "$RESULT" | tr ' ' '\n' | grep -E '^[0-9]+-[0-9]+$' | head -1)

        if [ -n "$NEW_ID" ] && [ "$NEW_ID" != "$LAST_ID" ]; then
            LAST_ID="$NEW_ID"

            # Extraire la réponse
            RESPONSE=$(echo "$RESULT" | tr ')' '\n' | grep -A1 "response" | tail -1 | tr -d ' "')

            echo ""
            echo "=== $(date '+%H:%M:%S') ==="
            if [ -n "$RESPONSE" ]; then
                echo "$RESPONSE"
            fi
        fi
    fi
done
