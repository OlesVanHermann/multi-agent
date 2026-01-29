#!/bin/bash
# watch.sh - Écoute les réponses d'un agent en temps réel via Redis Streams
# Usage: ./watch.sh <agent_id> [--history]
#        ./watch.sh 300          # Nouvelles réponses seulement
#        ./watch.sh 300 --history # Voir aussi l'historique

set -e

AGENT_ID=${1:-300}
STREAM="ma:agent:${AGENT_ID}:outbox"

# --history = commencer depuis le début, sinon depuis maintenant
if [ "$2" = "--history" ]; then
    LAST_ID="0-0"
    echo "Watching agent $AGENT_ID (with history)..."
else
    LAST_ID='$'
    echo "Watching agent $AGENT_ID (new messages only)..."
fi

echo "Stream: $STREAM"
echo "Press Ctrl+C to quit"
echo "---"

while true; do
    # XREAD avec timeout de 5 secondes
    result=$(redis-cli XREAD BLOCK 5000 STREAMS "$STREAM" "$LAST_ID" 2>/dev/null) || true

    if [ -n "$result" ]; then
        # Extraire tous les message IDs et prendre le dernier
        new_id=$(echo "$result" | grep -oE '[0-9]{13,}-[0-9]+' | tail -1)

        if [ -n "$new_id" ]; then
            LAST_ID="$new_id"

            # Afficher le message formaté
            echo ""
            echo "=== $(date '+%H:%M:%S') ==="

            # Extraire la réponse du message Redis
            response=$(echo "$result" | sed -n '/response/{n;p;}' | sed 's/^[0-9]*) //' | tr -d '"')

            if [ -n "$response" ]; then
                echo "$response"
            else
                # Fallback: afficher tout le résultat
                echo "$result" | tail -5
            fi
        fi
    fi
done
