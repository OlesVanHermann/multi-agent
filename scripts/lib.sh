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

# IDs des agents dont la session tmux tourne, un par ligne.
# A6 : le format d'ID n'est connu que d'ici — les appelants ne réécrivent
# jamais la regex de session.
list_live_agent_ids() {
    local session id
    while IFS= read -r session; do
        id="${session#agent-}"
        is_valid_agent_id "$id" && printf '%s\n' "$id"
    done < <(tmux list-sessions -F '#S' 2>/dev/null | grep '^agent-')
}

# Vérifie qu'un PID appartient bien au watchdog (healthcheck.py --watchdog).
# Ne jamais tuer un PID recyclé par un autre process : le fichier
# logs/watchdog.pid peut survivre à un reboot.
watchdog_pid_matches() {
    local pid="$1" args
    [ -n "$pid" ] || return 1
    args=$(ps -p "$pid" -o args= 2>/dev/null) || return 1
    case "$args" in
        *healthcheck.py*--watchdog*) return 0 ;;
        *) return 1 ;;
    esac
}

# Coordinateur d'un triangle NNN-YZZ : NNN-1ZZ.
# Retourne 1 pour un ID global ou pour le coordinateur lui-même.
triangle_master_id() {
    local agent_id="$1" triangle member suffix master
    if [[ ! "$agent_id" =~ ^([0-9]{3})-([0-9]{3})$ ]]; then
        return 1
    fi
    triangle="${BASH_REMATCH[1]}"
    member="${BASH_REMATCH[2]}"
    suffix="${member:1:2}"
    master="${triangle}-1${suffix}"
    [ "$agent_id" != "$master" ] || return 1
    printf '%s\n' "$master"
}

# Triangle auto-resolve — règle partagée send.sh / done.sh.
# Depuis un émetteur en triangle (NNN-XXX), une cible nue YYY est résolue en
# NNN-YYY (même triangle), avec priorité par vivacité tmux :
#   0. cible préfixée `=` (ex. `=100`) → JAMAIS résolue : adressage global
#      explicite. L'auto-resolve est un raccourci de confort ; sans cette
#      échappatoire, un Master global devenait structurellement injoignable
#      depuis un triangle dont le coordinateur local tourne ;
#   1. NNN-YYY tourne  → résolu (raccourci intra-triangle) ;
#   2. sinon YYY tourne → cible nue conservée (plan global, ex. Master 100 —
#      un triangle doit pouvoir signaler hors triangle, cf. z21 « Master +
#      Dev + Master 100 ») ;
#   3. sinon, si NNN-YYY est un membre connu (prompt présent) → résolu ;
#      sinon cible nue conservée : une simple fenêtre de redémarrage de
#      l'agent global ne doit pas détourner le message vers une inbox de
#      triangle que personne ne démarrera jamais.
# Cible finale sur stdout ; le WARNING éventuel part sur stderr.
resolve_triangle_target() {
    local from="$1" to="$2" caller="${3:-send.sh}"
    local triangle resolved base_dir
    # Adressage global explicite : `=YYY` court-circuite l'auto-resolve.
    if [[ "$to" == =* ]]; then
        printf '%s\n' "${to#=}"
        return
    fi
    if [[ "$from" =~ ^([0-9]+)-[0-9]+$ ]]; then
        triangle="${BASH_REMATCH[1]}"
        if [[ "$to" =~ ^[0-9]+$ ]]; then
            resolved="${triangle}-${to}"
            if tmux has-session -t "=$(agent_session_name "$resolved")" 2>/dev/null; then
                echo "[$caller] WARNING: auto-resolved $to -> $resolved (sender $from is in triangle $triangle)" >&2
                to="$resolved"
            elif ! tmux has-session -t "=$(agent_session_name "$to")" 2>/dev/null; then
                # Aucune des deux sessions ne tourne : ne résoudre que si le
                # membre de triangle existe réellement dans les prompts.
                base_dir="${BASE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
                if compgen -G "$base_dir/prompts/${triangle}*/${resolved}*" >/dev/null 2>&1; then
                    echo "[$caller] WARNING: auto-resolved $to -> $resolved (sender $from is in triangle $triangle)" >&2
                    to="$resolved"
                else
                    echo "[$caller] WARNING: $to conservé (aucun membre $resolved connu ; l'inbox globale sera rejouée)" >&2
                fi
            fi
        fi
    fi
    printf '%s\n' "$to"
}
