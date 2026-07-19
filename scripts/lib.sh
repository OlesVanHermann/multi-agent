#!/bin/bash
# lib.sh — Fonctions partagées entre les scripts shell.
#
# A6 : source unique de vérité du format d'ID agent côté shell.
# L'équivalent Python est scripts/agent-bridge/ids.py. Toute évolution
# du format se fait dans CES DEUX fichiers uniquement.
#
# Usage: source "$SCRIPT_DIR/lib.sh"

# Format d'ID agent : NNN ou NNN-NNN.
AGENT_ID_REGEX='^[0-9]{3}(-[0-9]{3})?$'

# Retourne 0 si l'ID est valide, 1 sinon (silencieux)
is_valid_agent_id() {
    [[ "$1" =~ $AGENT_ID_REGEX ]]
}

# Adressage canonique : l'identifiant complet suffit, sans préfixe d'installation.
agent_session_name() { printf 'agent-%s\n' "$1"; }
agent_status_key()   { printf 'agent:%s\n' "$1"; }
agent_inbox_key()    { printf 'agent:%s:inbox\n' "$1"; }
agent_outbox_key()   { printf 'agent:%s:outbox\n' "$1"; }

# Triangle auto-resolve — règle partagée send.sh / done.sh.
# Depuis un émetteur en triangle (NNN-XXX), une cible nue YYY est résolue en
# NNN-YYY (même triangle), avec priorité par vivacité tmux :
#   1. NNN-YYY tourne  → résolu (raccourci intra-triangle) ;
#   2. sinon YYY tourne → cible nue conservée (plan global, ex. Master 100 —
#      un triangle doit pouvoir signaler hors triangle, cf. z21 « Master +
#      Dev + Master 100 ») ;
#   3. sinon            → résolu (inbox triangle : rejouée au redémarrage
#      par le consumer group, comportement historique conservé).
# Cible finale sur stdout ; le WARNING éventuel part sur stderr.
resolve_triangle_target() {
    local from="$1" to="$2" caller="${3:-send.sh}"
    local triangle resolved
    if [[ "$from" =~ ^([0-9]+)-[0-9]+$ ]]; then
        triangle="${BASH_REMATCH[1]}"
        if [[ "$to" =~ ^[0-9]+$ ]]; then
            resolved="${triangle}-${to}"
            if tmux has-session -t "=$(agent_session_name "$resolved")" 2>/dev/null \
               || ! tmux has-session -t "=$(agent_session_name "$to")" 2>/dev/null; then
                echo "[$caller] WARNING: auto-resolved $to -> $resolved (sender $from is in triangle $triangle)" >&2
                to="$resolved"
            fi
        fi
    fi
    printf '%s\n' "$to"
}
