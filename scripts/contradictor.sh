#!/bin/bash
# Collecte bornée et envoi d'une conclusion Contradictor.
# Usage: ./scripts/contradictor.sh collect NNN
#        ./scripts/contradictor.sh send NNN
#        printf '%s' "$NEW_PROMPT" | ./scripts/contradictor.sh revise-prompt NNN

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 collect|send|revise-prompt NNN" >&2
    exit 2
fi

exec python3 "$SCRIPT_DIR/agent-bridge/contradictor.py" "$1" "$2"
