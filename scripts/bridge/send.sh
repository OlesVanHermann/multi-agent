#!/bin/bash
# send.sh - Envoie un message à un agent via Redis Streams
# Usage: ./send.sh <from_agent> <to_agent> <message>
#        ./send.sh 100 300 "go scaleway.com"
#        FROM_AGENT=100 ./send.sh 300 "go scaleway.com"  (legacy)

set -e

# Support both formats:
# 1. send.sh <from> <to> <message>  (new)
# 2. send.sh <to> <message>         (legacy, uses FROM_AGENT env var)

if [ $# -ge 3 ] && [[ "$1" =~ ^[0-9]+$ ]] && [[ "$2" =~ ^[0-9]+$ ]]; then
    # New format: send.sh 100 300 "message"
    FROM_AGENT=$1
    TO_AGENT=$2
    shift 2
    MESSAGE="$*"
else
    # Legacy format: send.sh 300 "message"
    TO_AGENT=$1
    shift 2>/dev/null || true
    FROM_AGENT=${FROM_AGENT:-cli}

    if [ $# -gt 0 ]; then
        MESSAGE="$*"
    else
        MESSAGE=$(cat)
    fi
fi

if [ -z "$TO_AGENT" ]; then
    echo "Usage: $0 <from_agent> <to_agent> <message>"
    echo "       $0 100 300 'go scaleway.com'"
    exit 1
fi

if [ -z "$MESSAGE" ]; then
    echo "Error: No message provided"
    exit 1
fi

TIMESTAMP=$(date +%s)

# Envoyer via Redis Streams (nouveau format)
redis-cli XADD "ma:agent:${TO_AGENT}:inbox" '*' \
    prompt "$MESSAGE" \
    from_agent "$FROM_AGENT" \
    timestamp "$TIMESTAMP" > /dev/null

echo "Sent to agent $TO_AGENT: ${MESSAGE:0:60}..."
