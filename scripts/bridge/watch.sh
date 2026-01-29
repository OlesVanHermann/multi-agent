#!/bin/bash
# watch.sh - Écoute les réponses d'un agent en temps réel via Redis Streams
# Usage: ./watch.sh <agent_id>
#        ./watch.sh 300

set -e

AGENT_ID=${1:-300}
STREAM="ma:agent:${AGENT_ID}:outbox"
LAST_ID='$'

echo "Watching agent $AGENT_ID responses (Ctrl+C to quit)..."
echo "Stream: $STREAM"
echo "---"

while true; do
    # XREAD avec timeout
    result=$(redis-cli XREAD BLOCK 5000 STREAMS "$STREAM" "$LAST_ID" 2>/dev/null)

    if [ -n "$result" ]; then
        # Extraire le message ID pour le prochain read
        LAST_ID=$(echo "$result" | grep -oE '[0-9]+-[0-9]+' | tail -1)

        # Afficher le message formaté
        echo ""
        echo "=== $(date '+%H:%M:%S') ==="
        # Extraire la réponse
        echo "$result" | grep -A1 "response" | tail -1 | sed 's/^[0-9]*) //'
        echo ""
    fi
done
