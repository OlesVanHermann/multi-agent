#!/bin/bash
# Assemble le prompt complet d'un agent x45 et l'affiche
# Usage: ./scripts/x45-run-agent.sh <agent_id>
# Exemple: ./scripts/x45-run-agent.sh 345
#
# Charge dans l'ordre : AGENT.md → system.md → memory.md → methodology.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
AGENT_ID="${1:?Usage: $0 <agent_id>}"
AGENT_DIR="$ROOT/prompts/$AGENT_ID"

if [ ! -d "$AGENT_DIR" ]; then
    echo "Erreur: agent $AGENT_ID introuvable ($AGENT_DIR)" >&2
    exit 1
fi

echo "=== Prompt assemblé pour Agent $AGENT_ID ==="
echo ""

# 1. AGENT.md (règles universelles)
if [ -f "$ROOT/prompts/AGENT.md" ]; then
    cat "$ROOT/prompts/AGENT.md"
    echo ""
    echo "---"
    echo ""
fi

# 2. system.md (contrat)
if [ -f "$AGENT_DIR/system.md" ]; then
    cat "$AGENT_DIR/system.md"
    echo ""
    echo "---"
    echo ""
else
    echo "⚠ MANQUANT: $AGENT_ID/system.md" >&2
fi

# 3. memory.md (contexte)
if [ -f "$AGENT_DIR/memory.md" ]; then
    cat "$AGENT_DIR/memory.md"
    echo ""
    echo "---"
    echo ""
else
    echo "⚠ MANQUANT: $AGENT_ID/memory.md" >&2
fi

# 4. methodology.md (méthodes)
if [ -f "$AGENT_DIR/methodology.md" ]; then
    cat "$AGENT_DIR/methodology.md"
else
    echo "⚠ MANQUANT: $AGENT_ID/methodology.md" >&2
fi
