#!/bin/bash
# inbox.sh - Affiche les messages dans l'inbox d'un agent
# Usage: ./inbox.sh <agent_id> [count]

AGENT_ID=${1:-300}
COUNT=${2:-10}

echo "Inbox for agent $AGENT_ID (last $COUNT messages):"
echo "Stream: ma:agent:${AGENT_ID}:inbox"
echo "---"

redis-cli XREVRANGE "ma:agent:${AGENT_ID}:inbox" + - COUNT "$COUNT" 2>/dev/null | \
while read -r line; do
    if [[ "$line" =~ ^[0-9]+-[0-9]+$ ]]; then
        echo ""
        echo "ID: $line"
    elif [[ "$line" == "prompt" ]]; then
        echo -n "  Prompt: "
    elif [[ "$line" == "from_agent" ]]; then
        echo -n "  From: "
    elif [[ "$line" == "timestamp" ]]; then
        echo -n "  Time: "
    elif [[ "$line" =~ ^[0-9]+$ ]] && [ ${#line} -eq 10 ]; then
        # Timestamp
        echo "$(date -d @"$line" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$line")"
    else
        echo "$line"
    fi
done

echo ""
