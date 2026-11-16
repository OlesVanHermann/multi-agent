#!/bin/bash
# agent.sh - Start/stop agents
# Usage: ./scripts/agent.sh start <agent_id|all>
#        ./scripts/agent.sh stop <agent_id|all>

set -e

# Raise open files limit (each agent = tmux session + claude + bridge)
ulimit -n 10240 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$BASE_DIR/setup/secrets.cfg" ]; then
    set -a
    eval "$(grep -E '^[A-Z_]+=' "$BASE_DIR/setup/secrets.cfg" | grep -v '^#')"
    set +a
fi
source "$SCRIPT_DIR/redis.sh"
source "$SCRIPT_DIR/lib.sh"
source "$SCRIPT_DIR/engines.sh"   # E1 : moteurs CLI (claude | codex)
BRIDGE_SCRIPT="$BASE_DIR/scripts/agent-bridge/agent.py"
LOG_DIR="$BASE_DIR/logs"
PROMPTS_DIR="$BASE_DIR/prompts"
PROFILES_DIR="$BASE_DIR/login"

# Réglages tmux pilotés par le panneau Login & Model (POST /api/config/tmux-size)
# et persistés sous prompts/tmux.<nom>. Trois paramètres indépendants.
# La hauteur n'est pas cosmétique : le TUI tourne en écran alterné, tmux ne
# garde aucun scrollback, donc la hauteur du pane décide seule du nombre de
# lignes de transcript que le dashboard peut afficher.
if [ -f "$PROMPTS_DIR/tmux.width" ]; then
    TMUX_COLS=$(cat "$PROMPTS_DIR/tmux.width" | tr -d '[:space:]')
fi
if [ -f "$PROMPTS_DIR/tmux.height" ]; then
    TMUX_ROWS=$(cat "$PROMPTS_DIR/tmux.height" | tr -d '[:space:]')
fi
if [ -f "$PROMPTS_DIR/tmux.history" ]; then
    TMUX_HISTORY=$(cat "$PROMPTS_DIR/tmux.history" | tr -d '[:space:]')
fi

# tmux n'applique history-limit qu'aux panes créés APRÈS le réglage : un
# `set-option -t <session>` posé après `new-session` laissait le pane de
# l'agent au défaut global (2000), jamais à la valeur voulue. On pose donc le
# global sur le serveur avant toute création de session.
apply_tmux_history_limit() {
    tmux start-server 2>/dev/null || return 0
    tmux set-option -g history-limit "${TMUX_HISTORY:-10000}" 2>/dev/null || true
}

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

validate_agent_id() {
    local id="$1"
    if ! is_valid_agent_id "$id"; then
        log_error "Invalid agent ID format: $id"
        return 1
    fi
}

# ── Helpers ──

is_protected() {
    # Protected: only 000 and its satellites (000-500, 000-900, etc.)
    local base="${1%%-*}"  # 345-500 → 345, 000-900 → 000
    [[ "$base" == "000" ]]
}

# Resolve x45 directory (plain, verbose, or sub-agent ID)
find_x45_dir() {
    local id="$1"
    # Exact match
    [ -d "$PROMPTS_DIR/$id" ] && echo "$PROMPTS_DIR/$id" && return 0
    # Verbose match: 341-analyse-archi-...
    for d in "$PROMPTS_DIR"/${id}-*/; do
        [ -d "$d" ] && echo "${d%/}" && return 0
    done
    # Sub-agent fallback: 300-100 → look up parent 300 (or 300-*)
    if [[ "$id" == *-* ]]; then
        local base="${id%%-*}"
        [ -d "$PROMPTS_DIR/$base" ] && echo "$PROMPTS_DIR/$base" && return 0
        for d in "$PROMPTS_DIR"/${base}-*/; do
            [ -d "$d" ] && echo "${d%/}" && return 0
        done
    fi
    return 1
}

# Migre à la volée un mono NNN historique vers la paire canonique NNN-1XX/2XX.
# L'opération est idempotente et le prompt/config historiques sont archivés par
# scaffold-mono-pair.py avant d'être recopiés sur l'agent principal.
ensure_mono_pair() {
    local id="${1%%-*}" dir type_target
    [[ "$id" =~ ^[0-9][0-9][0-9]$ ]] || return 0
    [ "$id" = "000" ] && return 0
    dir=$(find_x45_dir "$id") || return 0
    [ -f "$dir/mono-pair.json" ] && return 0
    [ -L "$dir/agent.type" ] || return 0
    type_target=$(basename "$(readlink "$dir/agent.type")")
    [ "$type_target" = "agent_mono.type" ] || return 0

    log_info "Migration mono $id -> $id-1${id:1:2} + $id-2${id:1:2}" >&2
    python3 "$SCRIPT_DIR/scaffold-mono-pair.py" "$id" \
        --base "$BASE_DIR" --directory-name "$(basename "$dir")" >&2
}

# Get all agent IDs for an x45 triangle (main + satellites)
get_triangle_ids() {
    local id="$1"
    ensure_mono_pair "$id" || return 1
    local dir
    dir=$(find_x45_dir "$id") || return 1
    local ids=()
    if [ ! -f "$dir/mono-pair.json" ]; then
        ids=("$id")
    fi
    # Local satellites (.md)
    for sat_link in "$dir"/${id}-[0-9][0-9][0-9].md; do
        [ -f "$sat_link" ] || continue
        ids+=("$(basename "$sat_link" .md)")
    done
    # Remote satellites (.remote)
    for rf in "$dir"/${id}-[0-9][0-9][0-9].remote; do
        [ -f "$rf" ] || continue
        local sat_id=$(basename "$rf" .remote)
        [[ " ${ids[*]} " == *" $sat_id "* ]] || ids+=("$sat_id")
    done
    echo "${ids[@]}"
}

# Resolve config file: x45 subdir > prompts root > default
# Usage: resolve_config "324-124" "login" → prints file content or empty
resolve_config() {
    local agent_id="$1" ext="$2"
    # 1. prompts/{dir_name}/{agent_id}.ext (x45 subdir — most specific).
    # Plusieurs répertoires portant le même préfixe peuvent coexister après
    # migration (ex. 000-hub-master + 000-super-master). Ne jamais prendre
    # aveuglément le premier : chercher celui qui porte réellement l'override.
    local base="${agent_id%%-*}"  # 324-124 → 324, 324 → 324
    local dir candidate found=""
    for dir in "$PROMPTS_DIR/$base" "$PROMPTS_DIR"/${base}-*/; do
        [ -d "$dir" ] || continue
        candidate="${dir%/}/${agent_id}.${ext}"
        if [ -f "$candidate" ] || [ -L "$candidate" ]; then
            if [ -n "$found" ] && [ "$found" != "$candidate" ]; then
                # stderr obligatoire : les appelants capturent stdout via
                # $( ) — sans redirection le diagnostic serait englouti.
                log_error "$agent_id: plusieurs overrides .$ext: $found et $candidate" >&2
                return 1
            fi
            found="$candidate"
        fi
    done
    if [ -n "$found" ]; then
        tr -d '[:space:]' < "$found"
        return
    fi
    # 2. prompts/{agent_id}.ext (flat)
    if [ -f "$PROMPTS_DIR/${agent_id}.${ext}" ]; then
        cat "$PROMPTS_DIR/${agent_id}.${ext}" | tr -d '[:space:]'
        return
    fi
    # 3. Override du groupe pour un satellite.
    if [[ "$agent_id" == *-* ]] && [ -f "$PROMPTS_DIR/${base}.${ext}" ]; then
        cat "$PROMPTS_DIR/${base}.${ext}" | tr -d '[:space:]'
        return
    fi
    # 4. prompts/default.ext (fallback)
    if [ -f "$PROMPTS_DIR/default.${ext}" ]; then
        cat "$PROMPTS_DIR/default.${ext}" | tr -d '[:space:]'
        return
    fi
}

# The engine is inferred from the effective model; users only change .model.
resolve_engine() {
    local agent_id="$1"
    engine_for_model "$(resolve_config "$agent_id" "model")"
}

# Timeout bridge optionnel : entier en secondes, borné pour éviter qu'un
# fichier projet invalide fasse mourir agent.py au parse de l'environnement.
resolve_agent_timeout() {
    local agent_id="$1" value
    value=$(resolve_config "$agent_id" "timeout")
    [ -z "$value" ] && return 0
    if [[ ! "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 30 ] || [ "$value" -gt 86400 ]; then
        log_error "$agent_id: timeout invalide '$value' (attendu: 30..86400 secondes)"
        return 1
    fi
    printf '%s\n' "$value"
}

# A8 : fenêtre bridge d'un agent — source unique (launch_agent_cli,
# reload-bridge). La fenêtre moteur (:0) n'est jamais touchée ici.
# resumed (identifiant non vide) : le CLI a repris sa session sauvegardée
# (AGENT_RESUMED=1) — le bridge rejoue « deviens agent » mais pas « Continue. ».
# start_bridge_window <agent_id> <cli> [resumed]
start_bridge_window() {
    local agent_id=$1 CLI=$2 resumed=${3:-}
    local SESSION_NAME="agent-$agent_id"
    local AGENT_TIMEOUT
    AGENT_TIMEOUT=$(resolve_agent_timeout "$agent_id") || return 1
    mkdir -p "$LOG_DIR/$agent_id"
    tmux new-window -t "$SESSION_NAME" -n bridge
    tmux send-keys -t "$SESSION_NAME:bridge" "cd '$BASE_DIR' && sleep 3 && AGENT_CLI='$CLI' ${resumed:+AGENT_RESUMED=1 }${AGENT_TIMEOUT:+RESPONSE_TIMEOUT='$AGENT_TIMEOUT' }REDIS_PASSWORD='${REDIS_PASSWORD:-}' REDIS_PORT='${REDIS_PORT:-6379}' HEALTH_TOKEN='${HEALTH_TOKEN:-}' python3 '$BRIDGE_SCRIPT' '$agent_id' 2>&1 | tee -a '$LOG_DIR/$agent_id/bridge.log'" Enter
    tmux select-window -t "$SESSION_NAME:0"
}

# Profil effectif du lancement (login1a → claude1a / codex1a selon le moteur).
# Écrit le profil (vide si aucun .login), ou logue l'erreur et retourne 1.
# resolve_launch_login <agent_id> <cli>
resolve_launch_login() {
    local agent_id="$1" cli="$2" login
    login=$(resolve_config "$agent_id" "login")
    if [ -n "$login" ]; then
        if ! engine_from_profile "$login" >/dev/null; then
            log_error "$agent_id: profil '$login' — moteur indéterminable (préfixe attendu: ${ENGINES[*]})" >&2
            return 1
        fi
        login=$(engine_effective_profile "$cli" "$login")
    fi
    printf '%s\n' "$login"
}

# E1 : construit la commande de lancement du CLI pour un agent.
# Écrit la commande sur stdout, ou logue l'erreur et retourne 1.
# build_launch_cmd <agent_id> [resume_id]  (resume_id : reprise, cf. update)
build_launch_cmd() {
    local agent_id="$1" resume_id="${2:-}"
    local cli model login effort cmd
    cli=$(resolve_engine "$agent_id")

    if ! engine_is_valid "$cli"; then
        log_error "$agent_id: moteur inconnu '$cli' (attendu: ${ENGINES[*]})"
        return 1
    fi

    model=$(resolve_config "$agent_id" "model")
    effort=$(resolve_config "$agent_id" "effort")
    login=$(resolve_launch_login "$agent_id" "$cli") || return 1

    if ! engine_model_is_compatible "$cli" "$model"; then
        log_error "$agent_id: modèle '$model' incompatible avec le moteur '$cli'"
        log_error "  (attendu: identifiant préfixé '$(engine_model_prefix "$cli")')"
        return 1
    fi

    # VERROU a — facturation. Un profil Codex authentifié par CLÉ API facturerait
    # au token, hors forfait. Sur un parc d'agents en continu, la note grimpe
    # avant qu'on s'en aperçoive : on refuse de démarrer.
    if [ "$cli" = "codex" ] && ! engine_codex_preflight "$PROFILES_DIR" "$login"; then
        log_error "$agent_id: préflight Codex refusé (voir ci-dessus)"
        return 1
    fi

    if ! cmd=$(engine_launch_cmd "$cli" "$PROFILES_DIR" "$login" "$model" "$effort" "$agent_id" "$resume_id"); then
        log_error "$agent_id: paramètres invalides (cli=$cli login=$login model=$model)"
        return 1
    fi
    printf '%s\n' "$cmd"
}

# Modèle, effort, advisor et ultracode d'un CLI fraîchement lancé — même
# séquence au démarrage (start_single) et à la reprise (update_single).
apply_cli_settings() {
    local agent_id=$1 SESSION_NAME=$2 CLI=$3 MODEL=$4 EFFORT=$5
    # Modèle + effort via la commande du CLI (modifiables en cours de session).
    # codex : picker /model piloté (les arguments seraient avalés comme prompt).
    engine_apply_model_effort "$SESSION_NAME" "$CLI" "$MODEL" "$EFFORT" || \
        log_warn "$agent_id: application modèle/effort incomplète (voir ci-dessus)"
    # Advisor : persisté par PROFIL dans le CLI, donc toujours envoyé (off compris).
    engine_apply_advisor "$SESSION_NAME" "$CLI" "$(resolve_config "$agent_id" "advisor")" || \
        log_warn "$agent_id: advisor non appliqué (voir ci-dessus)"
    # Ultracode : interrupteur de SESSION, jamais persisté par le CLI (repart à
    # off) — renvoyé à chaque démarrage quand il est configuré « on ».
    if [ "$(resolve_config "$agent_id" "ultracode" 2>/dev/null | tr -d "[:space:]")" = "on" ]; then
        engine_apply_ultracode "$SESSION_NAME" "$CLI" on || \
            log_warn "$agent_id: ultracode non appliqué (voir ci-dessus)"
    fi
}

# ── Session sauvegardée à l'arrêt (prompts/<dir>/<id>.session) ──

# Identifiant à reprendre au démarrage (vide : nouvelle session). Un fichier
# qui ne colle plus (profil ou moteur changé, contenu illisible) ou écarté par
# --fresh part dans removed/ : un arrêt ultérieur sans sauvegarde ne doit
# jamais le faire resservir. Journal sur stderr (l'appelant capture stdout).
# session_resume_for <agent_id> <cli> <login> [fresh]
session_resume_for() {
    local agent_id=$1 cli=$2 login=$3 fresh=${4:-} file out rc=0
    file=$(agent_session_file "$agent_id" "$PROMPTS_DIR")
    [ -e "$file" ] || return 0
    if [ -n "$fresh" ]; then
        session_file_archive "$file" "$BASE_DIR/removed" > /dev/null || true
        log_info "$agent_id: nouvelle session demandée (--fresh), $(basename "$file") archivé dans removed/" >&2
        return 0
    fi
    out=$(session_file_resume_id "$file" "$login" "$cli") || rc=$?
    if [ "$rc" -eq 0 ]; then
        printf '%s\n' "$out"
        return 0
    fi
    session_file_archive "$file" "$BASE_DIR/removed" > /dev/null || true
    log_warn "$agent_id: session sauvegardée écartée ($out) — nouvelle session, $(basename "$file") archivé dans removed/" >&2
    return 0
}

# Arrêt : quitte un CLI au repos par sa commande de sortie et sauvegarde sa
# session pour le start suivant. Jamais bloquant : agent occupé, question
# affichée, CLI qui ne quitte pas → arrêt sans sauvegarde (un fichier existant
# n'est pas touché ; il pointe encore la session en cours si elle a été reprise).
# save_session_on_stop <agent_id> <session>
save_session_on_stop() {
    local agent_id=$1 session=$2 cli profile blockers sid file agent_dir
    if agent_dir=$(find_x45_dir "$agent_id" 2>/dev/null) && [ -f "$agent_dir/remote.ssh" ]; then
        return 0   # agent distant : sa session vit sur l'autre machine
    fi
    cli=$(engine_running_cli "$session") || return 0   # CLI déjà sorti
    if ! profile=$(engine_running_profile "$session" "$cli"); then
        log_warn "$agent_id: profil du process illisible — arrêt sans sauvegarde de session"
        return 0
    fi
    blockers=$(agent_rest_blockers "$agent_id" "$session" "$cli")
    if [ -n "$blockers" ]; then
        log_warn "$agent_id pas au repos ($blockers) — arrêt sans sauvegarde de session"
        return 0
    fi
    # Plus aucune livraison pendant la sortie : le bridge s'arrête d'abord. Ses
    # messages non acquittés sont rejoués au prochain démarrage.
    if tmux list-windows -t "$session" -F '#{window_name}' 2>/dev/null | grep -qx bridge; then
        tmux kill-window -t "$session:bridge" 2>/dev/null || true
    fi
    sleep 1
    blockers=$(engine_rest_blockers "$session" "$cli" | paste -sd' ')
    if [ -n "$blockers" ]; then
        log_warn "$agent_id n'est plus au repos ($blockers) — arrêt sans sauvegarde de session"
        return 0
    fi
    if ! sid=$(engine_exit_session_id "$session" "$cli"); then
        log_warn "$agent_id: $cli n'a pas quitté après sa commande de sortie — arrêt sans sauvegarde de session"
        return 0
    fi
    if [ -z "$sid" ]; then
        log_warn "$agent_id: aucun identifiant de session imprimé par $cli — arrêt sans sauvegarde de session"
        return 0
    fi
    file=$(agent_session_file "$agent_id" "$PROMPTS_DIR")
    if session_file_write "$file" "$(basename "$profile")" "$cli" "$sid"; then
        log_ok "$agent_id: session $sid sauvegardée ($(basename "$profile"), $cli) dans ${file#"$BASE_DIR"/}"
    else
        log_warn "$agent_id: écriture de ${file#"$BASE_DIR"/} impossible — session non sauvegardée"
    fi
}

# Démarrage : identifiant de la session en cours relevé par la commande de
# statut du CLI et écrit dans <id>.session (lib.sh session_record_at_start).
# Jamais bloquant ; avant le bridge, qui enverra l'auto-init.
# record_session_at_start <agent_id> <session> <cli> [resumed]
record_session_at_start() {
    local agent_id=$1 session=$2 cli=$3 resumed=${4:-} sid rc=0 file
    sid=$(session_record_at_start "$agent_id" "$session" "$cli" "$PROMPTS_DIR") || rc=$?
    file=$(agent_session_file "$agent_id" "$PROMPTS_DIR")
    case "$rc" in
        0)
            if [ -n "$resumed" ] && [ "$sid" != "$resumed" ]; then
                log_warn "$agent_id: session reprise $resumed, $cli annonce $sid — fichier mis à jour"
            fi
            log_ok "$agent_id: session $sid relevée au démarrage dans ${file#"$BASE_DIR"/}" ;;
        1) log_warn "$agent_id: identifiant de session non relevé au démarrage ($cli)" ;;
        2) log_warn "$agent_id: profil du process illisible — session non enregistrée au démarrage" ;;
        *) log_warn "$agent_id: écriture de ${file#"$BASE_DIR"/} impossible au démarrage" ;;
    esac
    return 0
}

# Ouvre la session tmux d'un agent et y lance la commande du CLI.
# open_cli_session <session> <launch_cmd>
open_cli_session() {
    apply_tmux_history_limit
    tmux new-session -d -s "$1" -x "${TMUX_COLS:-110}" -y "${TMUX_ROWS:-54}"
    # CLAUDE_WRAPPER (optional): isolation prefix, e.g. "sudo -u agent-worker" or "firejail --profile=..."
    tmux send-keys -t "$1" "cd '$BASE_DIR' && unset CLAUDECODE && ${CLAUDE_WRAPPER:-} $2" Enter
}

# Lancement d'un agent — partagé par start_single et start_all : CLI dans la
# fenêtre :0 (en reprenant la session sauvegardée quand profil et moteur
# collent), modèle/effort/advisor/ultracode, puis bridge. Une reprise qui ne
# démarre pas (session introuvable dans le profil…) repart sur une nouvelle
# session. Renseigne LAUNCH_CLI et LAUNCH_RESUMED (identifiant repris ou vide).
# rc 1 : configuration invalide, rien n'est créé ; rc 2 : CLI pas prêt, la
# session est laissée à l'appelant ; rc 3 : bridge non démarré.
# launch_agent_cli <agent_id> [fresh]
LAUNCH_CLI=""
LAUNCH_RESUMED=""
launch_agent_cli() {
    local agent_id=$1 fresh=${2:-} SESSION="agent-$1"
    local MODEL EFFORT login resume_id LAUNCH_CMD file
    LAUNCH_CLI=$(resolve_engine "$agent_id")
    LAUNCH_RESUMED=""
    MODEL=$(resolve_config "$agent_id" "model")
    EFFORT=$(resolve_config "$agent_id" "effort")
    # Validation complète (moteur, profil, préflight codex) avant toute session.
    LAUNCH_CMD=$(build_launch_cmd "$agent_id") || return 1
    login=$(resolve_launch_login "$agent_id" "$LAUNCH_CLI") || return 1
    resume_id=$(session_resume_for "$agent_id" "$LAUNCH_CLI" "$login" "$fresh")
    if [ -n "$resume_id" ]; then
        LAUNCH_CMD=$(build_launch_cmd "$agent_id" "$resume_id") || return 1
    fi

    open_cli_session "$SESSION" "$LAUNCH_CMD"
    if [ -n "$resume_id" ]; then
        if wait_cli_resumed "$SESSION" "$LAUNCH_CLI" 60; then
            LAUNCH_RESUMED="$resume_id"
        else
            file=$(agent_session_file "$agent_id" "$PROMPTS_DIR")
            session_file_archive "$file" "$BASE_DIR/removed" > /dev/null || true
            log_warn "$agent_id: la reprise de $resume_id n'a pas démarré — nouvelle session, $(basename "$file") archivé dans removed/"
            tmux kill-session -t "$SESSION" 2>/dev/null || true
            LAUNCH_CMD=$(build_launch_cmd "$agent_id") || return 1
            open_cli_session "$SESSION" "$LAUNCH_CMD"
            wait_cli_ready "$SESSION" "$LAUNCH_CLI" 30 || return 2
        fi
    else
        wait_cli_ready "$SESSION" "$LAUNCH_CLI" 30 || return 2
    fi

    apply_cli_settings "$agent_id" "$SESSION" "$LAUNCH_CLI" "$MODEL" "$EFFORT"
    record_session_at_start "$agent_id" "$SESSION" "$LAUNCH_CLI" "$LAUNCH_RESUMED"
    # Prompt injection is handled by the bridge (agent.py auto-init) : nouvelle
    # session ou session reprise, modèle/effort ci-dessus puis « deviens agent ».
    # Timeout de réponse par agent : prompts/{dir}/{id}.timeout > prompts/{id}.timeout
    # > défaut bridge (300 s). Les devs codex sur tâches longues dépassent 300 s :
    # le bridge renvoyait alors un pane tronqué comme « réponse » au master.
    start_bridge_window "$agent_id" "$LAUNCH_CLI" "$LAUNCH_RESUMED" || return 3
    return 0
}

# ── Remote ──

start_remote() {
    # Start ONE remote session for agent_id. The triangle expansion loop
    # in do_start/start_all calls us once per member — do not iterate here.
    local agent_id=$1
    validate_agent_id "$agent_id" || return 1
    local agent_dir
    agent_dir=$(find_x45_dir "$agent_id") || return 1

    local rf="$agent_dir/${agent_id}.remote"
    if [ ! -f "$rf" ]; then
        log_warn "No .remote file for $agent_id in $(basename "$agent_dir")"
        return 1
    fi

    local ssh_cmd
    ssh_cmd=$(cat "$agent_dir/remote.ssh")
    if [[ ! "$ssh_cmd" =~ ^ssh[[:space:]] ]]; then
        log_error "Invalid remote.ssh content for $agent_id (must start with 'ssh ')"
        return 1
    fi
    local remote_session
    remote_session=$(cat "$rf" | tr -d '[:space:]')
    local SESSION_NAME="agent-${agent_id}"

    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_warn "$SESSION_NAME already exists, skipping"
        return 0
    fi

    log_info "Remote $agent_id → $remote_session"
    mkdir -p "$LOG_DIR/$agent_id"

    # Géométrie imposée par la session distante, donc PAS pilotée par TMUX_ROWS.
    # Local: -y 49 + status off → pane = 49 lines
    # Remote: status on + window 50 → pane = 49 (50 - status bar)
    # On attach: set status off → pane stays 49 (no resize, no SIGWINCH)
    apply_tmux_history_limit
    tmux new-session -d -s "$SESSION_NAME" -x "${TMUX_COLS:-220}" -y 49
    tmux set-option -t "$SESSION_NAME" status off
    tmux send-keys -t "$SESSION_NAME" "$ssh_cmd -t \"tmux attach -t $remote_session \\; set status off\"" Enter

    log_ok "$SESSION_NAME → $remote_session"
}

# ── Start ──

# start_single <agent_id> [fresh]   (fresh : ignorer la session sauvegardée)
start_single() {
    local agent_id=$1 fresh=${2:-}
    validate_agent_id "$agent_id" || return 1
    local SESSION_NAME="agent-$agent_id"

    # Démarrage demandé : le watchdog surveille de nouveau cet agent, après le
    # délai de grâce du démarrage (le bridge n'existe qu'en fin de lancement).
    set_desired_state "$agent_id" starting

    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_warn "$SESSION_NAME already exists, skipping"
        return
    fi

    if is_protected "$agent_id" && [ "${ALLOW_PROTECTED_000:-0}" != "1" ]; then
        log_warn "Skipping $agent_id (use ./scripts/infra.sh start for Architect)"
        return
    fi

    # Remote agent? Delegate to start_remote
    local agent_dir
    if agent_dir=$(find_x45_dir "$agent_id" 2>/dev/null) && [ -f "$agent_dir/remote.ssh" ]; then
        start_remote "$agent_id"
        return
    fi

    log_info "Starting agent $agent_id..."
    mkdir -p "$LOG_DIR/$agent_id"

    # E1 : moteur + modèle + login (résolution: subdir agent → prompts/ → default)
    local rc=0
    launch_agent_cli "$agent_id" "$fresh" || rc=$?
    case "$rc" in
        0) ;;
        2)
            log_error "Agent $agent_id: $LAUNCH_CLI did not start within 30s"
            tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
            return 1
            ;;
        *) return 1 ;;
    esac

    log_ok "Agent $agent_id started: $SESSION_NAME ($LAUNCH_CLI)${LAUNCH_RESUMED:+ — session $LAUNCH_RESUMED reprise}"
}

# E1 : marqueurs de « CLI démarré et prêt », lus dans markers.<cli>.yaml
# (clé ready_markers) — jamais codés en dur ici. Le cache évite un fork python3
# par tour de boucle de scrutation.
declare -A _READY_MARKERS_CACHE

cli_ready_markers() {
    local cli="$1"
    if [ -z "${_READY_MARKERS_CACHE[$cli]:-}" ]; then
        local m
        m=$(engine_marker_get "$cli" ready_markers) || return 1
        [ -z "$m" ] && return 1
        _READY_MARKERS_CACHE[$cli]="$m"
    fi
    printf '%s\n' "${_READY_MARKERS_CACHE[$cli]}"
}

wait_cli_ready() {
    # Wait until the CLI has finished booting in a tmux session.
    local session=$1
    local cli=${2:-$ENGINE_DEFAULT}
    local max_wait=${3:-30}  # max seconds to wait
    local elapsed=0

    # grep -F -e <m1> -e <m2> …  : équivaut au motif historique '❯|Try "'
    local -a grep_args=(-q -F)
    local marker found=0
    while IFS= read -r marker; do
        [ -n "$marker" ] || continue
        grep_args+=(-e "$marker")
        found=1
    done < <(cli_ready_markers "$cli")

    if [ "$found" -eq 0 ]; then
        log_error "Aucun ready_marker pour le moteur '$cli' — marqueurs non relevés ?"
        log_error "  → ./scripts/agent-bridge/capture-markers.sh $cli"
        return 1
    fi

    while [ $elapsed -lt $max_wait ]; do
        local pane_content
        pane_content=$(tmux capture-pane -t "$session:0" -p 2>/dev/null)
        if printf '%s' "$pane_content" | grep "${grep_args[@]}"; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1  # timeout
}

# Rétro-compat : ancien nom conservé (appelants externes éventuels)
wait_claude_ready() {
    wait_cli_ready "$1" "$ENGINE_DEFAULT" "${2:-30}"
}

start_all() {
    log_info "Auto-detecting agents from prompts/..."

    # Les installations mises à niveau peuvent encore contenir des monos
    # historiques. Les matérialiser avant le scan garantit deux sessions.
    local legacy_dir legacy_id
    for legacy_dir in "$PROMPTS_DIR"/[0-9][0-9][0-9] "$PROMPTS_DIR"/[0-9][0-9][0-9]-*; do
        [ -d "$legacy_dir" ] || continue
        legacy_id="$(basename "$legacy_dir")"
        ensure_mono_pair "${legacy_id:0:3}"
    done

    # Collect all agent IDs
    local agents=()

    # Format 1: flat prompts (pipeline standard) — prompts/XXX-*.md
    for prompt_file in "$PROMPTS_DIR"/[0-9][0-9][0-9]-*.md; do
        [ -f "$prompt_file" ] || continue
        local filename=$(basename "$prompt_file" .md)
        local agent_id="${filename%%-*}"
        is_protected "$agent_id" && continue
        # Skip duplicates (e.g. 390-rapport.md + 390-PLAN-MAXIMAL.md)
        [[ " ${agents[*]} " == *" $agent_id "* ]] && continue
        # Skip already running
        local SESSION_NAME="agent-$agent_id"
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            log_warn "$SESSION_NAME already exists, skipping"
            continue
        fi
        agents+=("$agent_id")
    done

    # Format 2: x45 directory prompts — prompts/XXX/ or prompts/XXX-name/
    for agent_dir in "$PROMPTS_DIR"/[0-9][0-9][0-9] "$PROMPTS_DIR"/[0-9][0-9][0-9]-*; do
        [ -d "$agent_dir" ] || continue
        local dir_name=$(basename "$agent_dir")
        # Extract numeric prefix (341 from 341-analyse-archi-...)
        local agent_id="${dir_name:0:3}"
        { [ -f "$agent_dir/${agent_id}-system.md" ] || [ -f "$agent_dir/system.md" ] || [ -f "$agent_dir/${dir_name}.md" ] || [ -f "$agent_dir/mono-pair.json" ] || ls "$agent_dir"/${agent_id}-*-system.md &>/dev/null || [ -f "$agent_dir/remote.ssh" ]; } || continue
        is_protected "$agent_id" && continue
        # Skip duplicates (already found in flat format or verbose duplicate)
        if [ ! -f "$agent_dir/mono-pair.json" ] && ! [[ " ${agents[*]} " == *" $agent_id "* ]]; then
            # Skip already running
            local SESSION_NAME="agent-$agent_id"
            if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
                log_warn "$SESSION_NAME already exists, skipping"
            else
                agents+=("$agent_id")
            fi
        fi

        # x45 satellites: find XXX-{suffix}.md symlinks (e.g. 345-500.md, 345-700.md)
        # Always scan satellites even if worker is already running
        for sat_link in "$agent_dir"/${agent_id}-[0-9][0-9][0-9].md; do
            [ -f "$sat_link" ] || continue
            local sat_name=$(basename "$sat_link" .md)  # e.g. 345-500
            is_protected "$sat_name" && continue
            [[ " ${agents[*]} " == *" $sat_name "* ]] && continue
            local SAT_SESSION="agent-$sat_name"
            if tmux has-session -t "$SAT_SESSION" 2>/dev/null; then
                log_warn "$SAT_SESSION already exists, skipping"
                continue
            fi
            agents+=("$sat_name")
        done
    done

    local total=${#agents[@]}
    if [ "$total" -eq 0 ]; then
        log_warn "No agents to start"
        return
    fi

    local BATCH_SIZE=6
    local AGENT_DELAY=1  # seconds between each agent start
    local batch_num=0

    for ((i=0; i<total; i+=BATCH_SIZE)); do
        local batch=("${agents[@]:i:BATCH_SIZE}")
        batch_num=$((batch_num + 1))
        log_info "Batch $batch_num: ${batch[*]}"

        # Sequential start: launch each agent, wait for ready, configure, then next
        local agent_count=0
        for agent_id in "${batch[@]}"; do
            # Remote agent? Handle separately (no Claude, no bridge)
            local agent_dir_check
            if agent_dir_check=$(find_x45_dir "$agent_id" 2>/dev/null) && [ -f "$agent_dir_check/remote.ssh" ]; then
                start_remote "$agent_id"
                agent_count=$((agent_count + 1))
                continue
            fi

            mkdir -p "$LOG_DIR/$agent_id"

            # E1 : moteur + commande de lancement (cf. build_launch_cmd)
            if ! build_launch_cmd "$agent_id" > /dev/null; then
                log_error "  Agent $agent_id: configuration invalide, non démarré"
                agent_count=$((agent_count + 1))
                continue
            fi

            # Comme start_single : après `stop all`, le marqueur d'arrêt
            # volontaire ferait ignorer l'agent par le watchdog pour toujours.
            set_desired_state "$agent_id" starting

            # CLI (session sauvegardée reprise si elle colle), réglages, bridge.
            local launch_rc=0
            launch_agent_cli "$agent_id" "$START_FRESH" || launch_rc=$?
            case "$launch_rc" in
                0) log_ok "  Agent $agent_id ready ($LAUNCH_CLI)${LAUNCH_RESUMED:+ — session $LAUNCH_RESUMED reprise}" ;;
                1) log_error "  Agent $agent_id: configuration invalide, non démarré" ;;
                2) log_error "  Agent $agent_id: $LAUNCH_CLI did not start within 30s" ;;
                *)
                    log_error "  Agent $agent_id: bridge non démarré"
                    continue
                    ;;
            esac

            # Delay between agents (skip after last in batch)
            agent_count=$((agent_count + 1))
            if [ $agent_count -lt ${#batch[@]} ]; then
                sleep $AGENT_DELAY
            fi
        done

        log_ok "Batch $batch_num done: ${#batch[@]} agents"
    done

    echo ""
    log_ok "Started $total agents ($batch_num batches of max $BATCH_SIZE)"
}

ensure_infra() {
    # Check-only: verify infra is up, start ONLY what's missing. Never stop/restart.
    local ok=true

    # Redis
    if ! $REDIS_CLI ping &>/dev/null 2>&1; then
        log_error "Redis not running. Start infra first: ./scripts/infra.sh start"
        ok=false
    fi

    # Dashboard
    if ! lsof -iTCP:8050 -sTCP:LISTEN &>/dev/null 2>&1; then
        log_info "Dashboard not running, starting..."
        "$SCRIPT_DIR/web.sh" start
    fi

    # Agent 000
    if ! tmux has-session -t "agent-000" 2>/dev/null; then
        log_warn "Agent 000 not running. Start infra first: ./scripts/infra.sh start"
    fi

    if [ "$ok" = false ]; then
        exit 1
    fi
}

do_start() {
    # Check infra is up (no stop/restart, no flush)
    ensure_infra

    local target=$1
    if [ -z "$target" ]; then
        show_help; exit 1
    elif [ "$target" = "all" ]; then
        start_all
    else
        shift
        for agent_id in "$target" "$@"; do
            # x45 triangle? expand to all satellites
            local tri_ids
            tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null)
            if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
                local group_dir group_kind="x45 triangle"
                group_dir=$(find_x45_dir "$agent_id" 2>/dev/null || true)
                [ -n "$group_dir" ] && [ -f "$group_dir/mono-pair.json" ] && group_kind="mono pair"
                log_info "$group_kind $agent_id: $tri_ids"
                for tid in $tri_ids; do
                    start_single "$tid" "$START_FRESH"
                done
            else
                start_single "$agent_id" "$START_FRESH"
            fi
        done
    fi
    echo ""
    echo "  List:   tmux ls | grep agent"
    echo "  Attach: tmux attach -t agent-<id>"
}

# ── Stop ──

# Arrêt volontaire : le watchdog (healthcheck.py) ne relance pas un agent dont
# desired_state=stopped. Le heartbeat survit à l'arrêt ; sans ce marqueur le
# watchdog prenait l'agent arrêté pour un agent en panne et le relançait.
# Démarrage : desired_state=starting + starting_at. Le CLI se configure avant
# que le bridge (et son /health) existe ; le watchdog ne compte aucun échec
# pendant WATCHDOG_STARTUP_GRACE_S et lève le marqueur au premier /health sain.
set_desired_state() {
    local agent_id=$1 state=$2
    case "$state" in
        stopped)
            $REDIS_CLI HSET "agent:$agent_id" desired_state stopped > /dev/null 2>&1 || true ;;
        starting)
            $REDIS_CLI HSET "agent:$agent_id" desired_state starting starting_at "$(date +%s)" > /dev/null 2>&1 || true ;;
        *)
            $REDIS_CLI HDEL "agent:$agent_id" desired_state starting_at > /dev/null 2>&1 || true ;;
    esac
}

# stop_single <agent_id> [nosave]   (nosave : ne pas sauvegarder la session)
stop_single() {
    local agent_id=$1 nosave=${2:-}
    local SESSION="agent-$agent_id"

    if is_protected "$agent_id" && [ "${ALLOW_PROTECTED_000:-0}" != "1" ]; then
        log_warn "Cannot stop $agent_id (use ./scripts/infra.sh stop)"
        return 1
    fi

    # Avant le kill : le watchdog ne doit jamais compter cet arrêt en échec.
    set_desired_state "$agent_id" stopped
    # CLI au repos : sortie propre, session sauvegardée pour le start suivant.
    if [ -z "$nosave" ] && tmux has-session -t "$SESSION" 2>/dev/null; then
        save_session_on_stop "$agent_id" "$SESSION" || true
    fi
    if tmux kill-session -t "$SESSION" 2>/dev/null; then
        log_ok "Killed $SESSION"
    else
        log_warn "$SESSION not found"
    fi
}

# Arrêt en parallèle (stop all, groupes x45/z21) : chaque sortie propre de CLI
# prend quelques secondes ; en série, un gros groupe dépasserait le délai du
# bouton stop du dashboard. rc 1 si un arrêt a échoué.
# stop_parallel <agent_id>...
stop_parallel() {
    local id pid rc=0
    local -a pids=()
    for id in "$@"; do
        stop_single "$id" &
        pids+=("$!")
    done
    for pid in "${pids[@]}"; do
        wait "$pid" || rc=1
    done
    return "$rc"
}

stop_all() {
    log_info "Stopping agents (000 is NEVER stopped)..."
    local session agent_id
    local -a ids=()
    while read -r session; do
        agent_id="${session#agent-}"
        if is_protected "$agent_id"; then
            log_warn "Skipping $session (protected)"
            continue
        fi
        set_desired_state "$agent_id" stopped
        ids+=("$agent_id")
    done < <(tmux ls 2>/dev/null | grep "^agent-" | cut -d: -f1)
    stop_parallel "${ids[@]}" || true

    # Update Redis status
    for key in $($REDIS_CLI KEYS "agent:*" 2>/dev/null | grep -E "^agent:[0-9]+(-[0-9]+)?$"); do
        $REDIS_CLI HSET "$key" status "stopped" > /dev/null 2>&1
    done
}

do_stop() {
    local target=$1
    if [ -z "$target" ]; then
        show_help; exit 1
    elif [ "$target" = "all" ]; then
        stop_all
    else
        shift
        for agent_id in "$target" "$@"; do
            # x45 triangle? expand to all satellites
            local tri_ids
            tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null)
            if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
                log_info "x45 triangle $agent_id: $tri_ids"
                stop_parallel $tri_ids
            else
                stop_single "$agent_id"
            fi
        done
    fi
    log_ok "Done"
}

# ── Restart ──

do_restart() {
    local target=$1
    if [ -z "$target" ]; then
        show_help; exit 1
    elif [ "$target" = "all" ]; then
        stop_all
        log_info "Waiting 5s before restarting..."
        sleep 5
        start_all
    else
        shift
        for agent_id in "$target" "$@"; do
            # x45 triangle? expand to all satellites
            local tri_ids
            tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null) || true
            if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
                log_info "x45 triangle $agent_id: $tri_ids"
                stop_parallel $tri_ids
                log_info "Waiting 5s before restarting..."
                sleep 5
                for tid in $tri_ids; do
                    start_single "$tid" "$START_FRESH"
                done
            else
                stop_single "$agent_id"
                log_info "Waiting 5s before restarting $agent_id..."
                sleep 5
                start_single "$agent_id" "$START_FRESH"
            fi
        done
    fi
    log_ok "Restart done"
}

# ── Reload bridge (A8) ──
# Recharge UNIQUEMENT le process bridge (fenêtre :bridge) sans toucher la
# fenêtre moteur (:0). Sûr par construction : le consumer group + le WAL
# rejouent tout message pending au redémarrage. Refuse un agent busy sauf
# FORCE_RELOAD=1 — tuer le bridge en plein tour ferait rejouer le prompt.

reload_bridge_single() {
    local agent_id=$1
    validate_agent_id "$agent_id" || return 1
    local SESSION_NAME="agent-$agent_id"

    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_warn "$SESSION_NAME not running — nothing to reload"
        return 1
    fi

    local status
    status=$($REDIS_CLI HGET "agent:$agent_id" status 2>/dev/null || true)
    if [ "$status" = "busy" ] && [ "${FORCE_RELOAD:-0}" != "1" ]; then
        log_warn "$agent_id est busy — reload refusé (FORCE_RELOAD=1 pour forcer)"
        return 1
    fi

    local CLI
    CLI=$(resolve_engine "$agent_id")
    if ! engine_is_valid "$CLI"; then
        log_error "$agent_id: moteur inconnu '$CLI'"
        return 1
    fi

    if tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' 2>/dev/null \
            | grep -qx bridge; then
        tmux send-keys -t "$SESSION_NAME:bridge" C-c 2>/dev/null || true
        sleep 1
        tmux kill-window -t "$SESSION_NAME:bridge" 2>/dev/null || true
    fi

    start_bridge_window "$agent_id" "$CLI" || return 1
    log_ok "Bridge reloaded for $agent_id (engine window untouched)"
}

do_reload_bridge() {
    local target=$1
    if [ -z "$target" ]; then
        show_help; exit 1
    elif [ "$target" = "all" ]; then
        tmux ls 2>/dev/null | grep "^agent-" | cut -d: -f1 | while read session; do
            local agent_id="${session#agent-}"
            if is_protected "$agent_id" && [ "${ALLOW_PROTECTED_000:-0}" != "1" ]; then
                log_warn "Skipping $agent_id (protected)"
                continue
            fi
            reload_bridge_single "$agent_id" || true
        done
    else
        shift
        for agent_id in "$target" "$@"; do
            local tri_ids
            tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null) || true
            if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
                log_info "x45 triangle $agent_id: $tri_ids"
                for tid in $tri_ids; do
                    reload_bridge_single "$tid" || true
                done
            else
                reload_bridge_single "$agent_id" || true
            fi
        done
    fi
    log_ok "Done"
}

# ── Update : relance du CLI en reprenant SA session ──
# Prendre une nouvelle version du CLI sans perdre la conversation : commande
# de sortie du CLI (exit_command des marqueurs, jamais Ctrl-C), lecture de l'identifiant que le CLI imprime en quittant,
# relance du même profil avec reprise, puis modèle/effort/advisor/ultracode
# comme au démarrage. La fenêtre bridge n'est pas touchée : pas de nouvel
# auto-init, la conversation continue.
# Pendant la relance, le pane 0 est un shell : un prompt collé là serait
# EXÉCUTÉ comme une commande. agent:<id>:cli_hold (avec TTL) fait patienter le
# bridge ; un bridge qui ne l'annonce pas dans bridge_caps est refusé.
# Aucun identifiant NOUVEAU à la sortie (session sans message, libellé du CLI
# changé) ou reprise qui ne démarre pas : repli sur un redémarrage complet,
# signalé par « UPDATE_RESULT … mode=restarted ».
# Ne se déclenche QUE sur un agent au repos : ni tour en cours, ni question ou
# menu affiché, ni commande en fond (même lecture du pane que le dashboard).
# Aucun forçage : quitter le CLI dans ces états perdrait le travail ou la
# réponse attendue.
# Même profil que celui qui tourne (claude1a, codex1a, claude3a…) : la session
# vit dans CE répertoire. Si la configuration a changé depuis le lancement
# (profil ou moteur), update refuse : c'est un restart.
# Codes retour : 0 fait (reprise ou repli) ; refus sans effet : 3 agent pas au
# repos, 4 bridge sans cli_hold (reload-bridge d'abord), 5 profil/moteur en
# cours ≠ configuration ; 1 erreur — le CLI tourne toujours.
UPDATE_HOLD_TTL=600
UPDATE_HOLD_KEY=""

# Raisons pour lesquelles l'agent n'est pas au repos, séparées par des espaces
# (vide = au repos) : statut du bridge + scan du pane.
# agent_rest_blockers <agent_id> <session> <cli>
agent_rest_blockers() {
    local agent_id=$1 session=$2 cli=$3 status reasons
    status=$($REDIS_CLI HGET "agent:$agent_id" status 2>/dev/null || true)
    case "$status" in
        busy|retrying) reasons="travaille" ;;
    esac
    reasons="$reasons $(engine_rest_blockers "$session" "$cli" | tr '\n' ' ')"
    printf '%s\n' "$reasons" | tr ' ' '\n' | grep . | awk '!seen[$0]++' | paste -sd' '
}

release_cli_hold() {
    [ -n "$UPDATE_HOLD_KEY" ] || return 0
    $REDIS_CLI DEL "$UPDATE_HOLD_KEY" > /dev/null 2>&1 || true
    UPDATE_HOLD_KEY=""
}

# Prêt après une reprise : CLI au premier plan, marqueur prêt affiché, plus de
# libellé de chargement. Le pane est vidé (clear -x) avant la relance : le
# texte de l'ancien TUI ne peut pas passer pour le nouveau.
# Un CLI qui n'est toujours pas au premier plan après 8 s est sorti (session
# introuvable dans le profil…) : échec sans attendre la fin du délai.
wait_cli_resumed() {
    local session=$1 cli=$2 max_wait=${3:-60} elapsed=0
    while [ "$elapsed" -lt "$max_wait" ]; do
        if engine_cli_running "$session" "$cli"; then
            if wait_cli_ready "$session" "$cli" 1 \
                && ! engine_resume_loading "$session" "$cli"; then
                return 0
            fi
        elif [ "$elapsed" -ge 8 ]; then
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

update_single() {
    local agent_id=$1
    validate_agent_id "$agent_id" || return 1
    local SESSION_NAME="agent-$agent_id"

    if is_protected "$agent_id" && [ "${ALLOW_PROTECTED_000:-0}" != "1" ]; then
        log_warn "Cannot update $agent_id (protected — ALLOW_PROTECTED_000=1)"
        return 1
    fi
    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_error "$SESSION_NAME not running — nothing to update (use start)"
        return 1
    fi
    local agent_dir
    if agent_dir=$(find_x45_dir "$agent_id" 2>/dev/null) && [ -f "$agent_dir/remote.ssh" ]; then
        log_error "$agent_id: agent distant — update non supporté"
        return 1
    fi

    local CLI MODEL EFFORT
    CLI=$(resolve_engine "$agent_id")
    MODEL=$(resolve_config "$agent_id" "model")
    EFFORT=$(resolve_config "$agent_id" "effort")
    if ! engine_is_valid "$CLI"; then
        log_error "$agent_id: moteur inconnu '$CLI'"
        return 1
    fi
    if ! engine_cli_running "$SESSION_NAME" "$CLI"; then
        local other
        for other in "${ENGINES[@]}"; do
            if [ "$other" != "$CLI" ] && engine_cli_running "$SESSION_NAME" "$other"; then
                log_warn "$agent_id: $other tourne, la configuration demande $CLI — changement de moteur en attente : ./scripts/agent.sh restart $agent_id"
                return 5
            fi
        done
        log_error "$agent_id: $CLI ne tourne pas dans $SESSION_NAME:0 — utiliser restart"
        return 1
    fi

    # Un bridge qui ne sait pas patienter collerait ses messages dans le shell :
    # refus. Sans fenêtre bridge, rien n'est livré au pane.
    if tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' 2>/dev/null | grep -qx bridge; then
        local caps
        caps=$($REDIS_CLI HGET "agent:$agent_id" bridge_caps 2>/dev/null || true)
        if [[ " $caps " != *" cli_hold "* ]]; then
            log_warn "$agent_id: bridge sans cli_hold — recharger d'abord : ./scripts/agent.sh reload-bridge $agent_id"
            return 4
        fi
    fi

    # Même profil que le process : la session à reprendre vit dans CE profil.
    local login running want
    login=$(resolve_launch_login "$agent_id" "$CLI") || return 1
    want="${login:+$PROFILES_DIR/$login}"
    running=$(engine_running_profile "$SESSION_NAME" "$CLI") || running=""
    if [ "$running" != "$want" ]; then
        log_warn "$agent_id: $CLI tourne sur le profil ${running:+$(basename "$running")}${running:-(inconnu)}, la configuration demande ${login:-(aucun)} — changement en attente : ./scripts/agent.sh restart $agent_id"
        return 5
    fi

    local blockers
    blockers=$(agent_rest_blockers "$agent_id" "$SESSION_NAME" "$CLI")
    if [ -n "$blockers" ]; then
        log_warn "$agent_id pas au repos ($blockers) — update refusé, rien n'est touché"
        return 3
    fi

    # Validation complète AVANT de toucher au CLI (profil, préflight codex…).
    build_launch_cmd "$agent_id" > /dev/null || return 1

    UPDATE_HOLD_KEY="agent:$agent_id:cli_hold"
    $REDIS_CLI SET "$UPDATE_HOLD_KEY" "update $(date +%s)" EX "$UPDATE_HOLD_TTL" > /dev/null 2>&1 || true
    # Une tâche prise juste avant le verrou passe busy dans la seconde : la
    # laisser se déclarer, puis revérifier. Plus au repos → annulé, CLI intact.
    sleep 2
    blockers=$(agent_rest_blockers "$agent_id" "$SESSION_NAME" "$CLI")
    if [ -n "$blockers" ]; then
        release_cli_hold
        log_warn "$agent_id n'est plus au repos ($blockers) — update annulé, rien n'est touché"
        return 3
    fi

    local sid=""
    if ! sid=$(engine_exit_session_id "$SESSION_NAME" "$CLI"); then
        release_cli_hold
        log_error "$agent_id: $CLI n'a pas quitté après sa commande de sortie — CLI intact"
        return 1
    fi

    local LAUNCH_CMD=""
    if [ -n "$sid" ] && LAUNCH_CMD=$(build_launch_cmd "$agent_id" "$sid"); then
        tmux send-keys -t "$SESSION_NAME:0" "clear -x; cd '$BASE_DIR' && unset CLAUDECODE && ${CLAUDE_WRAPPER:-} $LAUNCH_CMD" Enter
        if wait_cli_resumed "$SESSION_NAME" "$CLI" 60; then
            apply_cli_settings "$agent_id" "$SESSION_NAME" "$CLI" "$MODEL" "$EFFORT"
            release_cli_hold
            # Le fichier de session suit la session en cours : un arrêt brutal
            # ultérieur (agent occupé, crash) la reprendra au start suivant.
            session_file_write "$(agent_session_file "$agent_id" "$PROMPTS_DIR")" \
                "$(basename "$running")" "$CLI" "$sid" \
                || log_warn "$agent_id: fichier .session non écrit"
            log_ok "Agent $agent_id: $CLI relancé ($("$CLI" --version 2>/dev/null | head -1)), session $sid reprise"
            echo "UPDATE_RESULT agent=$agent_id mode=resumed session=$sid"
            return 0
        fi
        log_warn "$agent_id: la reprise de $sid n'a pas démarré — redémarrage complet"
    else
        log_warn "$agent_id: aucun identifiant de session imprimé par $CLI — redémarrage complet"
    fi

    # Repli : nouvelle session (fichier .session écarté), bridge relancé
    # (auto-init de l'agent). Le CLI est déjà sorti : rien à sauvegarder.
    release_cli_hold
    stop_single "$agent_id" nosave || true
    sleep 2
    if ! start_single "$agent_id" fresh; then
        log_error "$agent_id: redémarrage complet échoué"
        return 1
    fi
    echo "UPDATE_RESULT agent=$agent_id mode=restarted session="
    return 0
}

do_update() {
    local target=$1
    if [ -z "$target" ] || [ "$target" = "all" ]; then
        # Pas de « all » : chaque reprise interrompt un CLI, agent par agent.
        show_help; exit 1
    fi
    trap release_cli_hold EXIT
    local rc=0 agent_id tri_ids tid
    for agent_id in "$@"; do
        tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null) || true
        if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
            log_info "x45 triangle $agent_id: $tri_ids"
            for tid in $tri_ids; do
                update_single "$tid" || rc=$?
            done
        else
            update_single "$agent_id" || rc=$?
        fi
    done
    return $rc
}

# Nouvelle session (bouton « new session » du terminal) : /exit du CLI au
# repos, session sauvegardée écrasée (archivée dans removed/ par le start
# fresh, jamais reprise), relance sur une NOUVELLE conversation — réglages,
# identifiant relevé au démarrage, bridge relancé (« deviens agent »).
# Mêmes gardes que update : rien n'est touché si l'agent n'est pas au repos.
# Le moteur quitté est celui qui TOURNE ; le nouveau suit la configuration.
# rc 0 : nouvelle session ; 1 : erreur ; 3 : pas au repos ; 4 : bridge sans
# cli_hold ; 6 : agent protégé (000, démarré par infra.sh — jamais d'ici).
new_session_single() {
    local agent_id=$1
    validate_agent_id "$agent_id" || return 1
    local SESSION_NAME="agent-$agent_id"

    if is_protected "$agent_id"; then
        log_warn "$agent_id protégé — nouvelle session refusée (infra.sh gère 000)"
        return 6
    fi
    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_error "$SESSION_NAME not running — nothing to renew (use start --fresh)"
        return 1
    fi
    local agent_dir
    if agent_dir=$(find_x45_dir "$agent_id" 2>/dev/null) && [ -f "$agent_dir/remote.ssh" ]; then
        log_error "$agent_id: agent distant — nouvelle session non supportée"
        return 1
    fi
    local CLI
    if ! CLI=$(engine_running_cli "$SESSION_NAME"); then
        log_error "$agent_id: aucun CLI ne tourne dans $SESSION_NAME:0 — utiliser restart --fresh"
        return 1
    fi

    if tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' 2>/dev/null | grep -qx bridge; then
        local caps
        caps=$($REDIS_CLI HGET "agent:$agent_id" bridge_caps 2>/dev/null || true)
        if [[ " $caps " != *" cli_hold "* ]]; then
            log_warn "$agent_id: bridge sans cli_hold — recharger d'abord : ./scripts/agent.sh reload-bridge $agent_id"
            return 4
        fi
    fi

    local blockers
    blockers=$(agent_rest_blockers "$agent_id" "$SESSION_NAME" "$CLI")
    if [ -n "$blockers" ]; then
        log_warn "$agent_id pas au repos ($blockers) — nouvelle session refusée, rien n'est touché"
        return 3
    fi
    # Configuration du NOUVEAU lancement validée avant de toucher au CLI.
    build_launch_cmd "$agent_id" > /dev/null || return 1

    UPDATE_HOLD_KEY="agent:$agent_id:cli_hold"
    $REDIS_CLI SET "$UPDATE_HOLD_KEY" "new-session $(date +%s)" EX "$UPDATE_HOLD_TTL" > /dev/null 2>&1 || true
    sleep 2
    blockers=$(agent_rest_blockers "$agent_id" "$SESSION_NAME" "$CLI")
    if [ -n "$blockers" ]; then
        release_cli_hold
        log_warn "$agent_id n'est plus au repos ($blockers) — nouvelle session annulée, rien n'est touché"
        return 3
    fi

    local old=""
    if ! old=$(engine_exit_session_id "$SESSION_NAME" "$CLI"); then
        release_cli_hold
        log_error "$agent_id: $CLI n'a pas quitté après sa commande de sortie — CLI intact"
        return 1
    fi
    # Le CLI est sorti, le pane est un shell : le bridge doit disparaître
    # (stop) AVANT la levée du verrou, sinon il y collerait un message arrivé
    # pendant la sortie.
    stop_single "$agent_id" nosave || true
    release_cli_hold
    sleep 2
    if ! start_single "$agent_id" fresh; then
        log_error "$agent_id: démarrage de la nouvelle session échoué"
        return 1
    fi
    local new
    new=$(sed -n 3p "$(agent_session_file "$agent_id" "$PROMPTS_DIR")" 2>/dev/null || true)
    log_ok "Agent $agent_id: nouvelle session ${new:-(identifiant non relevé)}${old:+ — ancienne $old archivée}"
    echo "UPDATE_RESULT agent=$agent_id mode=new session=$new"
    return 0
}

do_new_session() {
    local target=$1
    if [ -z "$target" ] || [ "$target" = "all" ]; then
        # Pas de « all » : chaque nouvelle session efface une conversation.
        show_help; exit 1
    fi
    trap release_cli_hold EXIT
    local rc=0 agent_id tri_ids tid
    for agent_id in "$@"; do
        tri_ids=$(get_triangle_ids "$agent_id" 2>/dev/null) || true
        if [ -n "$tri_ids" ] && [ "$(echo $tri_ids | wc -w)" -gt 1 ]; then
            log_info "x45 triangle $agent_id: $tri_ids"
            for tid in $tri_ids; do
                new_session_single "$tid" || rc=$?
            done
        else
            new_session_single "$agent_id" || rc=$?
        fi
    done
    return $rc
}

# ── Help ──

show_help() {
    echo "Usage: $0 <start|stop|restart|reload-bridge|update|new-session> <agent_id|all>"
    echo ""
    echo "  $0 start 300       Start agent 300"
    echo "  $0 start 300 301   Start agents 300 and 301"
    echo "  $0 start all       Start all agents from prompts/"
    echo "  $0 stop 300        Stop agent 300"
    echo "  $0 stop all        Stop all (except 000)"
    echo "  $0 restart 300     Restart agent 300 (stop + 5s + start)"
    echo "  $0 restart all     Restart all (except 000)"
    echo "  $0 start 300 --fresh   Start on a NEW session (ignore the saved one)"
    echo "  $0 restart 300 --fresh Restart on a NEW session"
    echo "  $0 reload-bridge 300   Reload ONLY the bridge process (engine untouched)"
    echo "  $0 reload-bridge all   Reload all bridges (refuses busy agents)"
    echo "  $0 update 300-300      Restart ONLY the CLI, resuming its session (new CLI version)"
    echo "  $0 new-session 300-300 /exit the CLI and start a NEW session (saved one archived;"
    echo "                         a bare triangle id renews every member)"
    echo ""
    echo "  000 is protected — use infra.sh start / infra.sh stop"
    echo "  FORCE_RELOAD=1 reload-bridge <id> : reload even if agent is busy"
    echo "  update / new-session <id> refuse an agent not at rest (working, question, menu) — no override"
    echo ""
    echo "  stop saves the CLI session of an agent at rest in prompts/<dir>/<id>.session"
    echo "  (profile, engine, session id); start resumes it when profile and engine"
    echo "  still match. A busy agent is stopped without saving. New or resumed"
    echo "  session: model/effort are applied, then the bridge sends « deviens agent »."
}

# ── Main ──

ACTION=$1
shift 2>/dev/null || true

# --fresh (start / restart) : nouvelle session, la session sauvegardée est
# archivée dans removed/.
START_FRESH=""
_args=()
for _arg in "$@"; do
    if [ "$_arg" = "--fresh" ]; then
        START_FRESH=1
    else
        _args+=("$_arg")
    fi
done
set -- "${_args[@]}"
unset _arg _args

case "$ACTION" in
    start)   do_start "$@" ;;
    stop)    do_stop "$@" ;;
    restart) do_restart "$@" ;;
    reload-bridge) do_reload_bridge "$@" ;;
    update)  do_update "$@" ;;
    new-session) do_new_session "$@" ;;
    -h|--help|help|"") show_help ;;
    *)       log_error "Unknown action: $ACTION"; show_help; exit 1 ;;
esac
