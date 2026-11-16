#!/bin/bash
# engines.sh — Couche « moteur CLI » : source unique de vérité côté shell.
#
# Le framework ne parle pas à une API : il pilote un CLI agentique interactif
# dans tmux (send-keys / capture-pane). Historiquement ce CLI était toujours
# `claude`. Cette couche généralise la notion : un agent porte désormais trois
# dimensions résolues par resolve_config() —
#
#   .login  → profil d'authentification (répertoire dans login/)
#   .model  → identifiant de modèle       (ex. claude-opus-4-8, gpt-5.6-sol)
#   moteur  → déduit du préfixe du modèle (claude-* | gpt-*)
#
# L'équivalent Python est scripts/agent-bridge/engines.py (marqueurs UI, noms
# de process). Toute évolution se fait dans CES DEUX fichiers uniquement.
#
# Usage: source "$SCRIPT_DIR/engines.sh"

# Moteurs supportés
ENGINES=(claude codex)

# Moteur par défaut lorsqu'aucun modèle n'est imposé.
ENGINE_DEFAULT="claude"

# ── Validation ──

engine_is_valid() {
    local cli="$1"
    local e
    for e in "${ENGINES[@]}"; do
        [[ "$cli" == "$e" ]] && return 0
    done
    return 1
}

# Préfixe attendu de l'identifiant de modèle, par moteur.
# Garde-fou : empêche d'envoyer `/model gpt-5.6-sol` à Claude Code (échec
# silencieux dans le TUI : le modèle reste celui par défaut, sans erreur).
engine_model_prefix() {
    case "$1" in
        claude) printf 'claude-' ;;
        codex)  printf 'gpt-' ;;
    esac
}

engine_model_is_compatible() {
    local cli="$1" model="$2"
    [ -z "$model" ] && return 0          # pas de modèle imposé → CLI par défaut
    local prefix
    prefix=$(engine_model_prefix "$cli")
    [ -z "$prefix" ] && return 1
    [[ "$model" == "$prefix"* ]]
}

# ── Variables d'environnement d'authentification ──
# claude : CLAUDE_CONFIG_DIR   [Documenté: README.md + scripts/agent.sh]
# codex  : CODEX_HOME          [Documenté: developers.openai.com/codex/cli/reference]
engine_config_env() {
    case "$1" in
        claude) printf 'CLAUDE_CONFIG_DIR' ;;
        codex)  printf 'CODEX_HOME' ;;
    esac
}

# ── Drapeau « pas de confirmation humaine » ──
# claude : --dangerously-skip-permissions            [Documenté: README.md]
# codex  : --dangerously-bypass-approvals-and-sandbox
#          [Vérifié: codex-cli 0.144.1 — `codex --help`. Il n'existe PAS
#           d'alias --yolo dans cette version.]
# ⚠ MÊME exigence d'isolation que le README pour les deux moteurs.
engine_bypass_flag() {
    case "$1" in
        claude) printf -- '--dangerously-skip-permissions' ;;
        codex)  printf -- '--dangerously-bypass-approvals-and-sandbox' ;;
    esac
}

# ── Sélection du modèle ──
# claude : pas d'option de lancement fiable → slash-command `/model X` envoyée
#          au TUI après démarrage (comportement historique, conservé tel quel).
# codex  : option de lancement `--model X` (alias -m)
#          [Documenté: developers.openai.com/codex/models]
#          → on la privilégie : pas de danse send-keys, pas de menu à confirmer.
engine_model_via_slash() {
    return 0
}

# The model is the only user-facing engine selector. Login files keep naming a
# stable account slot (login1a..4b); each engine uses the matching
# CODEX_HOME (codex1a..4b), so agent prompts and memory never move.
engine_for_model() {
    case "$1" in
        gpt-*) printf 'codex\n' ;;
        *)     printf 'claude\n' ;;
    esac
}

engine_effective_profile() {
    local cli="$1" profile="$2" slot
    [ -z "$profile" ] && return 0
    slot="${profile#login}"; slot="${slot#claude}"; slot="${slot#codex}"
    printf '%s%s\n' "$cli" "$slot"
}

# ── Effort de raisonnement ──
# L'effort se règle PAR LA COMMANDE DU CLI, pas par une option de lancement :
# l'opérateur doit pouvoir le changer en cours d'exécution (dashboard).
# Cinq niveaux, lettres = noms réels des CLI (décision opérateur, 2026-10-09) :
#     L → low | M → medium | H → high | X → xhigh | MAX → max
# Ultracode n'est PAS un niveau : interrupteur séparé (engine_apply_ultracode),
# Claude uniquement. Ultra (codex) n'est jamais proposé.
# [Relevé: Claude Code 2.1.295 sur mx3, 2026-10-09 — « Set effort level to
#  low|medium|high|xhigh|max » ; codex-cli 0.160.1 — « Model changed to
#  <model> low|medium|high|xhigh|max »]
# Avant 2026-10-09 : L=medium M=high H=xhigh X=max U=ultracode — les fichiers
# existants sont convertis par patch/migrate-effort-letters.py.
engine_effort_level() {
    case "$2" in
        L) printf 'low' ;;
        M) printf 'medium' ;;
        H) printf 'high' ;;
        X) printf 'xhigh' ;;
        MAX) printf 'max' ;;
    esac
}

# Chiffre du niveau dans le picker codex « Select Reasoning Level »
# [Vérifié: codex-cli 0.144.4 ; confirmé 0.153.3 (capture opérateur mx6,
# 2026-09-04) et 0.160.1 (mx3, 2026-10-09) — 1.Low 2.Medium 3.High
# 4.Extra high 5.More reasoning… → Advanced Reasoning 1.Max]
engine_codex_effort_digit() {
    case "$1" in
        L) printf '1' ;;
        M) printf '2' ;;
        H) printf '3' ;;
        X) printf '4' ;;
        MAX) printf '5' ;;
    esac
}

# ── Ultracode (claude uniquement) ──
# Interrupteur de SESSION, indépendant du niveau : /effort <niveau> ne le
# change jamais, et il n'est jamais persisté (repart à off au redémarrage).
# [Relevé: Claude Code 2.1.292-2.1.295 sur mx3, 2026-10-09 — « /effort
#  ultracode on » → « Ultracode on (this session only): … Effort stays <n>. »,
#  footer « · ultracode · », bordure « ultracode » ; « /effort ultracode off »
#  → « Ultracode off. Effort stays <n>. »]
# engine_apply_ultracode <session> <cli> <on|off>
engine_apply_ultracode() {
    local session="$1" cli="$2" state="${3:-off}" target attempt before after marker
    [ "$cli" = "claude" ] || return 0
    case "$state" in on|off) ;; *) return 1 ;; esac
    target="${session}:0.0"
    marker="Ultracode $state"
    for attempt in 1 2 3; do
        before=$(tmux capture-pane -t "$target" -p -S -2000 2>/dev/null | grep -Fc "$marker" || true)
        tmux send-keys -t "$target" C-u; sleep 0.3
        tmux send-keys -t "$target" -l "/effort ultracode $state"
        sleep 0.8; tmux send-keys -t "$target" Enter; sleep 1.5
        after=$(tmux capture-pane -t "$target" -p -S -2000 2>/dev/null | grep -Fc "$marker" || true)
        [ "$after" -gt "$before" ] && return 0
    done
    echo "engine_apply_ultracode: /effort ultracode $state non confirmé ($session)" >&2
    return 1
}

# ── Application modèle + effort via le TUI (démarrage ET en cours de session) ──
# engine_apply_model_effort <session> <cli> <model_id> <effort(L|M|H|X|MAX)>
#
# claude : `/model <id>` (argument direct) puis `/effort <niveau>`.
#          [Vérifié: TUI réel — /effort accepte l'argument, statut « ● high »]
# codex  : les arguments de /model sont AVALÉS COMME PROMPT (vérifié 0.144.4,
#          le modèle répond poliment et rien ne change) — seul le picker
#          fonctionne : /model ⏎ → chiffre du modèle ⏎ → chiffre du niveau ⏎.
#          Le chiffre du modèle est PARSÉ dans le pane (l'ordre de la liste
#          change entre versions) ; modèle vide → entrée « (current) ».
engine_apply_model_effort() {
    # Défaut = H (high), le même que le dashboard quand aucun fichier .effort
    # n'existe (avant 2026-10-09 la lettre de high était M).
    local session="$1" cli="$2" model="$3" effort="${4:-H}"
    local target="${session}:0.0"
    case "$cli" in
        claude)
            if [ -n "$model" ]; then
                tmux send-keys -t "$target" -l "/model $model"
                sleep 0.5; tmux send-keys -t "$target" Enter; sleep 3
            fi
            local lvl attempt before_count after_count
            lvl=$(engine_effort_level "$cli" "$effort")
            if [ -n "$lvl" ]; then
                # Juste après /model, le re-rendu du TUI peut MANGER la frappe
                # (constaté au démarrage : /effort n'apparaît jamais, sans
                # erreur). Comme le bridge : vérifier l'effet réel — le footer
                # affiche « <niveau> · /effort » quand c'est pris — et
                # réessayer, composer nettoyé (C-u) avant chaque tentative.
                for attempt in 1 2 3; do
                    # Ne jamais valider sur une ANCIENNE confirmation encore
                    # visible dans le scrollback : une frappe avalée serait
                    # déclarée réussie si le niveau avait déjà été utilisé.
                    before_count=$(tmux capture-pane -t "$target" -p -S -2000 2>/dev/null \
                        | grep -Fc "Set effort level to $lvl" || true)
                    tmux send-keys -t "$target" C-u; sleep 0.3
                    tmux send-keys -t "$target" -l "/effort $lvl"
                    sleep 0.8; tmux send-keys -t "$target" Enter; sleep 1.5
                    # Ligne de résultat du TUI : « Set effort level to <lvl> … »
                    # (l'indicateur du footer n'est pas rendu en permanence).
                    after_count=$(tmux capture-pane -t "$target" -p -S -2000 2>/dev/null \
                        | grep -Fc "Set effort level to $lvl" || true)
                    if [ "$after_count" -gt "$before_count" ]; then
                        return 0
                    fi
                done
                echo "engine_apply_model_effort: /effort $lvl non confirmé ($session)" >&2
                return 1
            fi
            ;;
        codex)
            [ -z "$model" ] && [ -z "$effort" ] && return 0
            tmux send-keys -t "$target" C-u; sleep 0.3
            tmux send-keys -t "$target" -l "/model"
            sleep 0.5; tmux send-keys -t "$target" Enter
            local i pane="" digit=""
            for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
                pane=$(tmux capture-pane -t "$target" -p 2>/dev/null)
                printf '%s' "$pane" | grep -q "Select Model and Effort" && break
                sleep 0.5
            done
            if ! printf '%s' "$pane" | grep -q "Select Model and Effort"; then
                echo "engine_apply_model_effort: picker /model non ouvert ($session)" >&2
                return 1
            fi
            if [ -n "$model" ]; then
                # Insensible à la casse : codex-cli 0.160.1 affiche le nom
                # d'affichage (« 5. GPT-5.6-Sol », « 2. GPT-6-Astra ») et plus
                # l'identifiant configuré (gpt-5.6-sol, gpt-6-astra).
                # [Relevé: picker /model codex-cli 0.160.1, codex1a sur ma2 et
                #  TUI sur mx3, 2026-10-07 — sans -i, modèle « introuvable »,
                #  effort jamais appliqué, agent resté sur « GPT-6.1-Sol default »]
                digit=$(printf '%s' "$pane" | grep -ioE "[0-9]+\. ${model}[^a-zA-Z0-9.-]" | head -1 | grep -oE '^[0-9]+')
            else
                digit=$(printf '%s' "$pane" | grep -E '\(current\)' | grep -oE '[0-9]+\.' | head -1 | tr -d '.')
            fi
            if [ -z "$digit" ]; then
                tmux send-keys -t "$target" Escape
                echo "engine_apply_model_effort: modèle '$model' introuvable dans le picker ($session)" >&2
                return 1
            fi
            # Un chiffre SÉLECTIONNE ET CONFIRME instantanément dans les pickers
            # codex (vérifié 0.144.4) — un Enter supplémentaire validerait
            # l'entrée surlignée de l'écran suivant (Low par défaut).
            tmux send-keys -t "$target" -l "$digit"
            for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
                pane=$(tmux capture-pane -t "$target" -p 2>/dev/null)
                printf '%s' "$pane" | grep -q "Select Reasoning Level" && break
                sleep 0.5
            done
            if ! printf '%s' "$pane" | grep -q "Select Reasoning Level"; then
                echo "engine_apply_model_effort: écran d'effort non atteint ($session)" >&2
                return 1
            fi
            local lvl_digit
            lvl_digit=$(engine_codex_effort_digit "$effort")
            tmux send-keys -t "$target" -l "${lvl_digit:-3}"
            if [ "$effort" = "MAX" ]; then
                # 5. More reasoning… ouvre Advanced Reasoning : 1=Max (2=Ultra
                # n'est jamais proposé — décision opérateur, 2026-10-09), puis
                # Enter confirme le sous-choix.
                # [Relevé: TUI codex-cli 0.144.x sur mx6, 2026-07-28 ; 0.160.1
                #  sur mx3, 2026-10-07 — à contre-relever à chaque montée de
                #  version du picker]
                for i in 1 2 3 4 5 6 7 8 9 10; do
                    pane=$(tmux capture-pane -t "$target" -p 2>/dev/null)
                    printf '%s' "$pane" | grep -q "Advanced Reasoning" && break
                    sleep 0.5
                done
                if ! printf '%s' "$pane" | grep -q "Advanced Reasoning"; then
                    tmux send-keys -t "$target" Escape
                    echo "engine_apply_model_effort: écran Advanced Reasoning non atteint ($session)" >&2
                    return 1
                fi
                tmux send-keys -t "$target" -l "1"
                sleep 0.3
                tmux send-keys -t "$target" Enter
            fi
            sleep 1
            ;;
    esac
}

# ── Advisor (claude uniquement) ──
# Catalogue dynamique : prompts/<nom>.advisor → <nom>.model ; la valeur lue
# (identifiant claude-…) est passée telle quelle à `/advisor`, aucune liste
# n'est figée ici — le CLI décide de ce qu'il accepte.
# [Relevé: TUI Claude Code 2.1.292 — `/advisor claude-sonnet-5-5` → « Advisor
#  set to Sonnet 5.5 » ; `/advisor off` → « Advisor disabled » ; refus →
#  « <id> cannot be used as an advisor. Valid options: … » ou « Invalid
#  advisor model: Model '<x>' not found ». Le choix est aussi
#  persisté dans advisorModel du settings.json du PROFIL : plusieurs agents
#  partagent un profil, donc chaque démarrage envoie explicitement la valeur
#  de l'agent, « off » compris.]
# [Relevé: mx30, 2026-11-10 — `/advisor claude-fable-5-2` : Claude Code
#  2.1.319 → « claude-fable-5-2 cannot be used as an advisor. Valid options:
#  fable, opus, sonnet, off » (`fable` → Fable 5.1) ; Claude Code 2.1.322 →
#  « Advisor set to Fable 5.2 » (`fable` → Fable 5.2). Une session lancée
#  sur un binaire < 2.1.322 refuse donc fable-5-2.advisor : engine_apply_advisor
#  le signale et l'advisor prend effet au redémarrage sur le binaire à jour.]

# engine_apply_advisor <session> <cli> <model_id>  (vide → off)
engine_apply_advisor() {
    local session="$1" cli="$2" value="${3:-off}" target attempt before after marker
    [ "$cli" = "claude" ] || return 0
    target="${session}:0.0"
    if [ "$value" = "off" ]; then marker="Advisor disabled"; else marker="Advisor set to"; fi
    for attempt in 1 2 3; do
        before=$(tmux capture-pane -t "$target" -p -S -2000 2>/dev/null | grep -Fc "$marker" || true)
        tmux send-keys -t "$target" C-u; sleep 0.3
        tmux send-keys -t "$target" -l "/advisor $value"
        sleep 0.8; tmux send-keys -t "$target" Enter; sleep 1.5
        after=$(tmux capture-pane -t "$target" -p -S -2000 2>/dev/null | grep -Fc "$marker" || true)
        [ "$after" -gt "$before" ] && return 0
        # Deux formes de refus relevées : identifiant connu mais non éligible,
        # ou identifiant inconnu (« Invalid advisor model: Model 'x' not found »).
        if tmux capture-pane -t "$target" -p 2>/dev/null \
            | grep -Fq -e "$value cannot be used as an advisor" -e "Model '$value' not found"; then
            echo "engine_apply_advisor: $value refusé par le CLI ($session)" >&2
            return 1
        fi
    done
    echo "engine_apply_advisor: /advisor $value non confirmé ($session)" >&2
    return 1
}

# ── Répertoire temporaire privé ──
# engine_private_tmpdir <cli> <owner> : TMPDIR propre à un agent (ou session
# keepalive) pour les moteurs qui en ont besoin, vide sinon. Miroir de
# engines.private_tmpdir (Python). Codex supprime au démarrage les répertoires
# d'outils $TMPDIR/arg0/* qu'il juge abandonnés : partagé, ce nettoyage
# emportait apply_patch et le wrapper sandbox des autres Codex (mx81,
# 2026-10-10). /tmp/codex-* est exclu du vieillissement par tmpfiles.
engine_private_tmpdir() {
    local cli="$1" owner="$2"
    [ "$cli" = "codex" ] || return 0
    [[ "$owner" =~ ^[A-Za-z0-9_-]+$ ]] || return 0
    printf '/tmp/codex-%s\n' "$owner"
}

# Identifiant de session des deux moteurs : UUID strict. Il finit dans une
# ligne de shell (send-keys) et dans prompts/<dir>/<id>.session.
# engine_session_id_is_valid <id>
engine_session_id_is_valid() {
    [[ "${1:-}" =~ ^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$ ]]
}

# ── Construction de la commande de lancement ──
# engine_launch_cmd <cli> <profiles_dir> <login_profile> <model> [effort] [owner] [resume_id]
# Écrit sur stdout la commande complète à passer à `tmux send-keys`.
# Retourne 1 (et n'écrit rien) si une validation échoue.
# Une seule commande, sans `&&` de premier niveau : agent.sh la préfixe par
# CLAUDE_WRAPPER (confinement OS), qui doit couvrir le CLI lui-même.
engine_launch_cmd() {
    local cli="$1" profiles_dir="$2" login="$3" model="$4" effort="${5:-}" owner="${6:-}" resume_id="${7:-}"

    engine_is_valid "$cli" || return 1

    if [ -n "$login" ] && [[ ! "$login" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        return 1
    fi
    if [ -n "$model" ] && [[ ! "$model" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
        return 1
    fi
    # Identifiant injecté dans une ligne de shell (send-keys) : UUID strict.
    if [ -n "$resume_id" ] && ! engine_session_id_is_valid "$resume_id"; then
        return 1
    fi
    engine_model_is_compatible "$cli" "$model" || return 1

    local cmd=""

    # VERROU c — l'environnement. Une OPENAI_API_KEY qui traîne dans le shell
    # ferait basculer Codex en facturation au token, sans le dire. On la retire
    # de l'environnement du CLI et de tout ce qu'il lancera.
    # [Vérifié: codex-cli 0.144.1 — `env -u … codex …` parse]
    if [ "$cli" = "codex" ] && [ "${CODEX_ALLOW_API_KEY:-0}" != "1" ]; then
        cmd="env -u OPENAI_API_KEY -u CODEX_API_KEY "
    fi

    local tmpdir
    tmpdir=$(engine_private_tmpdir "$cli" "$owner")
    if [ -n "$tmpdir" ]; then
        cmd+="TMPDIR=$tmpdir "
    fi

    if [ -n "$login" ]; then
        cmd+="$(engine_config_env "$cli")=$profiles_dir/$login "
    fi
    # Le TMPDIR privé est créé PAR la commande lancée : un préfixe
    # `mkdir … && cli` ne confinerait que mkdir sous CLAUDE_WRAPPER et lancerait
    # le CLI hors du wrapper. `sh -c … exec` : même utilisateur, même sandbox,
    # puis le CLI remplace le shell (process au premier plan et environnement
    # inchangés pour engine_cli_running / engine_running_profile).
    if [ -n "$tmpdir" ]; then
        cmd+="sh -c 'mkdir -p \"\$TMPDIR\" && exec \"\$0\" \"\$@\"' "
    fi
    # Reprise d'une conversation (agent.sh update) — même session, même profil.
    # claude : option `--resume <id>`, ajoutée en fin de commande
    #          [Vérifié: Claude Code 2.1.322 — `claude --help` ; TUI réel mx5
    #           2026-11-10, conversation rouverte]
    # codex  : SOUS-COMMANDE `resume <id>`, donc juste après le binaire ; elle
    #          accepte les mêmes options que le lancement
    #          [Vérifié: codex-cli 0.167.0 — `codex resume --help` ; TUI réel mx5
    #           2026-11-10 avec bypass, --no-alt-screen et -c]
    cmd+="$cli"
    if [ -n "$resume_id" ] && [ "$cli" = "codex" ]; then
        cmd+=" resume $resume_id"
    fi
    cmd+=" $(engine_bypass_flag "$cli")"

    # Both TUIs receive the model after startup through `/model`.

    # VERROU b — le drapeau. Même si un login par clé API a échappé au préflight
    # (trousseau inaccessible, CODEX_SKIP_LOGIN_CHECK=1), Codex refusera de
    # démarrer autrement qu'en ChatGPT.
    # [Documenté: developers.openai.com/codex/config-reference — forced_login_method]
    # [Vérifié: codex-cli 0.144.1 — valeur TOML nue, pas de guillemets à échapper
    #  dans le send-keys tmux]
    if [ "$cli" = "codex" ] && [ "${CODEX_ALLOW_API_KEY:-0}" != "1" ]; then
        cmd+=" -c forced_login_method=chatgpt"
    fi

    if [ -n "$resume_id" ] && [ "$cli" = "claude" ]; then
        cmd+=" --resume $resume_id"
    fi

    printf '%s\n' "$cmd"
}

# ── Sortie du CLI et reprise de session (agent.sh update) ───────────────────

# Le CLI tourne-t-il au premier plan du pane 0 ? Noms de process lus dans
# markers.<cli>.yaml (process_names) — un shell au premier plan = CLI sorti.
# engine_cli_running <session> <cli>
engine_cli_running() {
    local session="$1" cli="$2" current name
    current=$(tmux display-message -t "${session}:0.0" -p '#{pane_current_command}' 2>/dev/null) \
        || return 1
    while IFS= read -r name; do
        [ -n "$name" ] && [ "$current" = "$name" ] && return 0
    done < <(engine_marker_get "$cli" process_names)
    return 1
}

# Quitte le CLI par SA commande de sortie (exit_command des marqueurs), composer
# vidé d'abord (C-u). Jamais Ctrl-C : décision opérateur 2026-11-13 — la double
# frappe Ctrl-C ne quittait pas (Claude Code 2.1.296 et 2.1.322, mx6), alors que
# la commande quitte et imprime la ligne de reprise. Envoi unique ; attente de
# la sortie au plus 10 s, sinon échec sans autre frappe (CLI intact).
# [Vérifié: TUI réels mx6 2026-11-13 — Claude Code 2.1.296 et 2.1.322, codex-cli
#  0.167.0 : sortie en ~2 s, identifiant de reprise lu par engine_resume_ids.]
# engine_exit_cli <session> <cli>
engine_exit_cli() {
    local session="$1" cli="$2" target="${1}:0.0" cmd i
    cmd=$(engine_marker_get "$cli" exit_command)
    [ -n "$cmd" ] || return 1
    tmux send-keys -t "$target" C-u 2>/dev/null || return 1
    sleep 0.3
    tmux send-keys -t "$target" -l "$cmd" 2>/dev/null || return 1
    sleep 0.5
    tmux send-keys -t "$target" Enter 2>/dev/null || return 1
    for i in $(seq 1 20); do
        sleep 0.5
        engine_cli_running "$session" "$cli" || return 0
    done
    return 1
}

# Profil sur lequel le CLI tourne RÉELLEMENT : répertoire de la variable
# d'auth du moteur (CLAUDE_CONFIG_DIR / CODEX_HOME) lue dans l'environnement du
# process au premier plan du pane. La configuration (.login) peut avoir changé
# depuis le lancement : seul le process fait foi pour reprendre SA session.
# [Vérifié: mx5 2026-11-12 — Claude Code 2.1.296/2.1.303 et codex-cli 0.162.1 :
#  claude1a, claude3a, claude4a, codex1a lus sur les agents en cours]
# engine_running_profile <session> <cli>  → chemin du profil, ou rc 1
engine_running_profile() {
    local session="$1" cli="$2" var pane_pid fg value
    var=$(engine_config_env "$cli")
    [ -n "$var" ] || return 1
    pane_pid=$(tmux display-message -t "${session}:0.0" -p '#{pane_pid}' 2>/dev/null) || return 1
    fg=$(ps -o tpgid= -p "$pane_pid" 2>/dev/null | tr -d ' ')
    [ -n "$fg" ] && [ "$fg" != "-1" ] && [ -r "/proc/$fg/environ" ] || return 1
    value=$(tr '\0' '\n' < "/proc/$fg/environ" | grep -m1 "^${var}=") || return 1
    printf '%s\n' "${value#*=}"
}

# Raisons pour lesquelles le CLI n'est PAS au repos (une par ligne, vide = au
# repos) : même scan de pane que la couleur du dashboard, plus les marqueurs
# d'approbation et de messages en file (engines.rest_blockers).
# engine_rest_blockers <session> <cli>
engine_rest_blockers() {
    python3 "$ENGINES_PY" rest-blockers "$1" --cli "$2" 2>/dev/null || echo etat_illisible
}

# Identifiants de reprise présents dans un texte de pane (stdin, capture -J),
# un par ligne, dans l'ordre. Motif : resume_hint_pattern du moteur.
# engine_resume_ids <cli>  < capture
engine_resume_ids() {
    python3 "$ENGINES_PY" resume-ids --cli "$1" 2>/dev/null
}

# Identifiant de la session EN COURS, lu par la commande de statut du CLI
# (status_command / status_session_pattern des marqueurs), puis fenêtre de
# statut refermée (status_dismiss_key ; non applicable = rien à fermer).
# Sécurité en plus de engine_exit_session_id : relevé dès le démarrage.
# Seul un identifiant APPARU après la commande compte (scrollback ignoré).
# engine_status_session_id <session> <cli>  → identifiant (stdout), ou rc 1
engine_status_session_id() {
    local session="$1" cli="$2" target="${1}:0.0" cmd dismiss before ids i sid=""
    cmd=$(engine_marker_get "$cli" status_command)
    [ -n "$cmd" ] || return 1
    # Valeur « non applicable » = motif inerte : jamais une touche à envoyer.
    dismiss=$(engine_marker_get "$cli" status_dismiss_key | grep -v '__NEVER__')
    before=$(tmux capture-pane -t "$target" -p -J -S - 2>/dev/null \
        | python3 "$ENGINES_PY" status-ids --cli "$cli" 2>/dev/null | grep -c . || true)
    tmux send-keys -t "$target" C-u 2>/dev/null || return 1
    sleep 0.3
    tmux send-keys -t "$target" -l "$cmd" 2>/dev/null || return 1
    sleep 0.6
    tmux send-keys -t "$target" Enter 2>/dev/null || return 1
    for i in $(seq 1 20); do
        sleep 0.5
        ids=$(tmux capture-pane -t "$target" -p -J -S - 2>/dev/null \
            | python3 "$ENGINES_PY" status-ids --cli "$cli" 2>/dev/null || true)
        if [ "$(printf '%s\n' "$ids" | grep -c . || true)" -gt "${before:-0}" ]; then
            sid=$(printf '%s\n' "$ids" | grep . | tail -1)
            break
        fi
    done
    if [ -n "$dismiss" ]; then
        tmux send-keys -t "$target" "$dismiss" 2>/dev/null || true
        sleep 0.5
    fi
    engine_session_id_is_valid "$sid" || return 1
    printf '%s\n' "$sid"
}

# Quitte le CLI par sa commande de sortie et écrit l'identifiant de session
# qu'il imprime en quittant. Seul un identifiant APPARU à cette sortie compte :
# un ancien, resté dans le scrollback, n'est jamais repris.
# rc 1 : le CLI n'a pas quitté (intact). rc 0 sans sortie : aucun identifiant.
# Partagé par `agent.sh update` (reprise immédiate) et `agent.sh stop`
# (prompts/<dir>/<id>.session, reprise au start suivant).
# engine_exit_session_id <session> <cli>
engine_exit_session_id() {
    local session="$1" cli="$2" before ids after
    before=$(tmux capture-pane -t "${session}:0" -p -J -S - 2>/dev/null \
        | engine_resume_ids "$cli" | grep -c . || true)
    engine_exit_cli "$session" "$cli" || return 1
    sleep 1   # la ligne de reprise suit la sortie de l'écran du TUI
    ids=$(tmux capture-pane -t "${session}:0" -p -J -S - 2>/dev/null \
        | engine_resume_ids "$cli" || true)
    after=$(printf '%s\n' "$ids" | grep -c . || true)
    if [ "${after:-0}" -gt "${before:-0}" ]; then
        printf '%s\n' "$ids" | grep . | tail -1
    fi
    return 0
}

# Moteur qui tourne RÉELLEMENT au premier plan du pane 0 (vide si aucun).
# engine_running_cli <session>
engine_running_cli() {
    local cli
    for cli in "${ENGINES[@]}"; do
        if engine_cli_running "$1" "$cli"; then
            printf '%s\n' "$cli"
            return 0
        fi
    done
    return 1
}

# Le pane affiche-t-il encore le chargement d'une session reprise ?
# Libellés : resume_loading_markers (inertes quand __NON_APPLICABLE__).
# engine_resume_loading <session> <cli>
engine_resume_loading() {
    local session="$1" cli="$2" pane marker
    pane=$(tmux capture-pane -t "${session}:0.0" -p 2>/dev/null) || return 1
    while IFS= read -r marker; do
        [ -n "$marker" ] && printf '%s' "$pane" | grep -qF -- "$marker" && return 0
    done < <(engine_marker_get "$cli" resume_loading_markers)
    return 1
}

# ── Profils de login ────────────────────────────────────────────────────────
# Le répertoire login/<profil>/ n'a pas la même structure selon le moteur
# (CLAUDE_CONFIG_DIR vs CODEX_HOME). Plutôt qu'une 4e dimension de config,
# le PRÉFIXE du nom de profil porte le moteur : claude1a → claude, codex2b → codex.
# Pendant Python : engines.profile_engine() / engines.is_valid_profile().

ENGINES_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agent-bridge/engines.py"

# Moteur d'un profil. Écrit le moteur sur stdout, ou retourne 1 si inconnu.
engine_from_profile() {
    local profile="$1" e
    [ -z "$profile" ] && return 1
    case "$profile" in login[1-4][ab]) printf 'slot\n'; return 0 ;; esac
    for e in "${ENGINES[@]}"; do
        case "$profile" in
            "$e"*) printf '%s\n' "$e"; return 0 ;;
        esac
    done
    return 1
}

# Nom de profil valide : <moteur><chiffre><lettre>  (claude1a, codex2b…)
engine_profile_is_valid() {
    local profile="$1" e
    [[ "$profile" =~ ^login[1-4][ab]$ ]] && return 0
    for e in "${ENGINES[@]}"; do
        [[ "$profile" =~ ^${e}[0-9][a-z]$ ]] && return 0
    done
    return 1
}

# ── Lecture d'un marqueur UI ────────────────────────────────────────────────
# Délègue à engines.py : une seule implémentation du parsing YAML + de la
# validation fail-fast. Une valeur par ligne sur stdout.
engine_marker_get() {
    local cli="$1" key="$2"
    python3 "$ENGINES_PY" get "$key" --cli "$cli" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════════════
# FACTURATION — le forfait ChatGPT, pas l'API à l'usage
#
# Codex accepte DEUX modes d'authentification :
#   « Sign in with ChatGPT » → usage décompté sur l'abonnement (ce qu'on veut)
#   « Provide your own API key » → facturation au token (ce qu'on ne veut PAS)
#
# Trois façons de basculer SILENCIEUSEMENT sur la facturation à l'usage :
#   1. un `codex login` passé fait avec une clé API, encore en cache
#   2. OPENAI_API_KEY présent dans l'environnement du shell
#   3. CODEX_API_KEY idem
#
# Sur 8 agents qui tournent en continu, ça se compte en centaines d'euros avant
# qu'on s'en aperçoive. Trois verrous, donc :
#   a. préflight  : refus de démarrer si le profil est authentifié par clé API
#   b. lancement  : -c forced_login_method=chatgpt
#   c. environnement : env -u OPENAI_API_KEY -u CODEX_API_KEY
#
# Opt-in explicite pour la facturation à l'usage : CODEX_ALLOW_API_KEY=1
# ═══════════════════════════════════════════════════════════════════════════

# Libellés exacts de `codex login status` (écrits sur stderr).
# [Documenté: openai/codex — codex-rs/cli/src/login.rs:440,449,456]
# [Vérifié: codex-cli 0.144.1]
CODEX_AUTH_API_KEY='Logged in using an API key'
CODEX_AUTH_CHATGPT='Logged in using ChatGPT'

# engine_codex_preflight <profiles_dir> <login_profile>
# Vérifie que CE profil est authentifié par ChatGPT. Retourne 1 + message sur
# stderr sinon. Le préflight est PAR PROFIL : chaque compte a son CODEX_HOME.
engine_codex_preflight() {
    local profiles_dir="$1" login="$2"
    local codex_bin="${CODEX_BIN:-codex}"
    local codex_home status rc=0

    if [ "${CODEX_SKIP_LOGIN_CHECK:-0}" = "1" ]; then
        return 0   # conteneurs / trousseau inaccessible ; les verrous b et c tiennent
    fi

    if ! command -v "$codex_bin" >/dev/null 2>&1; then
        echo "Codex CLI introuvable : $codex_bin" >&2
        return 1
    fi

    if [ -n "$login" ]; then
        codex_home="$profiles_dir/$login"
    else
        codex_home="${CODEX_HOME:-$HOME/.codex}"
    fi

    status=$(CODEX_HOME="$codex_home" "$codex_bin" login status 2>&1) || rc=$?

    if [ "$rc" -ne 0 ]; then
        echo "Profil '$login' non authentifié ($codex_home)." >&2
        echo "  → CODEX_HOME='$codex_home' codex login --device-auth   (« Sign in with ChatGPT » par code)" >&2
        return 1
    fi

    # Opt-in explicite : facturation à l'usage assumée.
    [ "${CODEX_ALLOW_API_KEY:-0}" = "1" ] && return 0

    # Tester la clé API EN PREMIER : un diagnostic mixte ne doit pas être pris
    # pour un login ChatGPT au seul motif qu'il mentionne « ChatGPT ».
    if printf '%s' "$status" | grep -qF "$CODEX_AUTH_API_KEY"; then
        echo "Profil '$login' authentifié par CLÉ API → facturation au token, hors forfait." >&2
        echo "  → CODEX_HOME='$codex_home' codex logout && CODEX_HOME='$codex_home' codex login --device-auth" >&2
        echo "  → puis se connecter avec « Sign in with ChatGPT » (URL + code)" >&2
        echo "  (Pour assumer la facturation à l'usage : CODEX_ALLOW_API_KEY=1)" >&2
        return 1
    fi

    if printf '%s' "$status" | grep -qF "$CODEX_AUTH_CHATGPT"; then
        return 0
    fi

    echo "Profil '$login' : méthode d'authentification inattendue — $status" >&2
    echo "  → CODEX_HOME='$codex_home' codex login --device-auth   (« Sign in with ChatGPT » par code)" >&2
    return 1
}
