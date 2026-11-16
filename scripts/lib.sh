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

# ── Session CLI sauvegardée à l'arrêt : prompts/<dir>/<id>.session ──────────
#
# `agent.sh stop` quitte un CLI au repos par sa commande de sortie, lit
# l'identifiant de session qu'il imprime et l'écrit ici ; le start suivant
# reprend cette session si le profil et le moteur n'ont pas changé.
# Trois lignes :
#   <profil>        profil EFFECTIF du process (claude3a, codex1a…)
#   <moteur>        un moteur de ENGINES
#   <identifiant>   UUID de la session
# Lu au chemin EXACT, jamais en cascade comme .model/.login : un satellite
# 300-100 ne reprend jamais la session de 300. Fichier d'état local : ignoré
# par git, jamais synchronisé vers le hub.
# Requiert engines.sh (engine_is_valid, engine_session_id_is_valid).

# Répertoire de prompts de l'agent : parmi prompts/NNN et prompts/NNN-*, celui
# qui porte ses fichiers (.md, .history, -system.md, .session), sinon le
# premier existant, sinon prompts/ (agents à plat).
# agent_prompt_dir <agent_id> <prompts_dir>
agent_prompt_dir() {
    local id="$1" prompts="$2" base="${1%%-*}" dir first=""
    for dir in "$prompts/$base" "$prompts/$base"-*/; do
        dir="${dir%/}"
        [ -d "$dir" ] || continue
        [ -n "$first" ] || first="$dir"
        if [ -e "$dir/$id.md" ] || [ -e "$dir/$id.history" ] \
            || [ -e "$dir/$id-system.md" ] || [ -e "$dir/$id.session" ]; then
            printf '%s\n' "$dir"
            return 0
        fi
    done
    printf '%s\n' "${first:-$prompts}"
}

# agent_session_file <agent_id> <prompts_dir>
agent_session_file() {
    printf '%s/%s.session\n' "$(agent_prompt_dir "$1" "$2")" "$1"
}

# Écrit le fichier : mode 600, remplacement atomique. rc 1 si une valeur est
# invalide (rien n'est écrit).
# session_file_write <file> <profil> <moteur> <identifiant>
session_file_write() {
    local file="$1" profile="$2" cli="$3" sid="$4" tmp
    [[ "$profile" =~ ^[A-Za-z0-9_-]+$ ]] || return 1
    engine_is_valid "$cli" || return 1
    engine_session_id_is_valid "$sid" || return 1
    tmp=$(mktemp "${file}.XXXXXX") || return 1
    chmod 600 "$tmp"
    printf '%s\n%s\n%s\n' "$profile" "$cli" "$sid" > "$tmp" && mv -f "$tmp" "$file"
}

# Identifiant de la session en cours relevé AU DÉMARRAGE (commande de statut
# du CLI) et écrit aussitôt — sécurité en plus de la sortie : un arrêt qui ne
# peut pas le relire (agent occupé, commandes en fond, CLI qui ne quitte pas)
# laisse un fichier qui pointe déjà la conversation en cours. Profil : celui
# du PROCESS, comme à l'arrêt.
# session_record_at_start <agent_id> <session> <cli> <prompts_dir>
#   rc 0 : identifiant écrit (stdout) ; 1 : non relevé ; 2 : profil illisible ;
#   3 : écriture impossible
session_record_at_start() {
    local agent_id="$1" session="$2" cli="$3" prompts_dir="$4" sid profile
    sid=$(engine_status_session_id "$session" "$cli") || return 1
    profile=$(engine_running_profile "$session" "$cli") || return 2
    session_file_write "$(agent_session_file "$agent_id" "$prompts_dir")" \
        "$(basename "$profile")" "$cli" "$sid" || return 3
    printf '%s\n' "$sid"
}

# Identifiant à reprendre pour ce profil et ce moteur.
# rc 0 : identifiant sur stdout ; rc 1 : pas de fichier ;
# rc 2 : fichier qui ne colle pas, raison sur stdout.
# session_file_resume_id <file> <profil> <moteur>
session_file_resume_id() {
    local file="$1" want_profile="$2" want_cli="$3"
    local profile="" cli="" sid="" extra=""
    [ -f "$file" ] || return 1
    { IFS= read -r profile; IFS= read -r cli; IFS= read -r sid; IFS= read -r extra; } \
        < "$file" || true
    if [ -z "$profile" ] || [ -n "$extra" ] || ! engine_is_valid "$cli" \
        || ! engine_session_id_is_valid "$sid"; then
        echo "fichier illisible"
        return 2
    fi
    if [ "$cli" != "$want_cli" ]; then
        echo "moteur $cli enregistré, $want_cli configuré"
        return 2
    fi
    if [ "$profile" != "$want_profile" ]; then
        echo "profil $profile enregistré, ${want_profile:-(aucun)} configuré"
        return 2
    fi
    printf '%s\n' "$sid"
}

# Archive le fichier dans removed/ (jamais de suppression) et écrit sa
# destination. Un fichier écarté ne doit plus resservir après un arrêt fait
# sans sauvegarde.
# session_file_archive <file> <removed_dir>
session_file_archive() {
    local file="$1" removed="$2" dest
    [ -e "$file" ] || return 0
    mkdir -p "$removed" || return 1
    dest="$removed/$(date +%Y%m%d_%H%M%S)_$(basename "$file")"
    [ -e "$dest" ] && dest="$dest.$$"
    mv "$file" "$dest" && printf '%s\n' "$dest"
}
