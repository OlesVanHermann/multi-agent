#!/bin/bash
# send.sh - Envoie un message à un agent via Redis Streams
# Usage: ./send.sh <to_agent_id> <message>
#        ./send.sh 300 "Analyse le fichier README.md"
#        echo "mon prompt" | ./send.sh 300

set -e

TO_AGENT=$1
shift 2>/dev/null || true

if [ -z "$TO_AGENT" ]; then
    echo "Usage: $0 <to_agent_id> <message>"
    echo "       echo 'message' | $0 <to_agent_id>"
    exit 1
fi

# Message depuis args ou stdin
if [ $# -gt 0 ]; then
    MESSAGE="$*"
else
    MESSAGE=$(cat)
fi

if [ -z "$MESSAGE" ]; then
    echo "Error: No message provided"
    exit 1
fi

FROM_AGENT=${FROM_AGENT:-cli}
TIMESTAMP=$(date +%s)

# Envoyer via Redis Streams (nouveau format)
redis-cli XADD "ma:agent:${TO_AGENT}:inbox" '*' \
    prompt "$MESSAGE" \
    from_agent "$FROM_AGENT" \
    timestamp "$TIMESTAMP" > /dev/null

echo "Sent to agent $TO_AGENT: ${MESSAGE:0:60}..."
