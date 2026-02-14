#!/bin/bash
#
# Orchestrator - Pousse "go" au Master toutes les X secondes
#
INTERVAL=${1:-60}

echo "Orchestrator started (interval: ${INTERVAL}s)"
echo "Pushing 'go' to Master (100)..."

while true; do
    redis-cli RPUSH "ma:inject:100" "go" > /dev/null 2>&1
    sleep "$INTERVAL"
done
