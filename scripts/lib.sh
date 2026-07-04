#!/bin/bash
# lib.sh — Fonctions partagées entre les scripts shell.
#
# A6 : source unique de vérité du format d'ID agent côté shell.
# L'équivalent Python est scripts/agent-bridge/ids.py. Toute évolution
# du format se fait dans CES DEUX fichiers uniquement.
#
# Usage: source "$SCRIPT_DIR/lib.sh"

# Format d'ID agent : NNN ou NNN-NNN (ex. 300, 345-500)
AGENT_ID_REGEX='^[0-9]{3}(-[0-9]{3})?$'

# Retourne 0 si l'ID est valide, 1 sinon (silencieux)
is_valid_agent_id() {
    [[ "$1" =~ $AGENT_ID_REGEX ]]
}
