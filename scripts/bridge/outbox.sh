#!/bin/bash
# outbox.sh - Affiche les messages dans l'outbox d'un agent
# Usage: ./outbox.sh <agent_id> [count]

AGENT_ID=${1:-300}
COUNT=${2:-10}

echo "Outbox for agent $AGENT_ID (last $COUNT messages):"
echo "Stream: ma:agent:${AGENT_ID}:outbox"
echo "---"

redis-cli XREVRANGE "ma:agent:${AGENT_ID}:outbox" + - COUNT "$COUNT" 2>/dev/null | \
while read -r line; do
    if [[ "$line" =~ ^[0-9]+-[0-9]+$ ]]; then
        echo ""
        echo "ID: $line"
    elif [[ "$line" == "response" ]]; then
        echo -n "  Response: "
    elif [[ "$line" == "to_agent" ]]; then
        echo -n "  To: "
    elif [[ "$line" == "from_agent" ]]; then
        echo -n "  From: "
    elif [[ "$line" == "chars" ]]; then
        echo -n "  Chars: "
    elif [[ "$line" == "timestamp" ]]; then
        echo -n "  Time: "
    elif [[ "$line" =~ ^[0-9]+$ ]] && [ ${#line} -eq 10 ]; then
        # Timestamp
        echo "$(date -d @"$line" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$line")"
    else
        # Truncate long responses
        if [ ${#line} -gt 100 ]; then
            echo "${line:0:100}..."
        else
            echo "$line"
        fi
    fi
done

echo ""
