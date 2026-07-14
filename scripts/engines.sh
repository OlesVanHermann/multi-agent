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
# stable account slot (claude1a..4b); Codex transparently uses the matching
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
    slot="${profile#claude}"; slot="${slot#codex}"
    printf '%s%s\n' "$cli" "$slot"
}

# ── Effort de raisonnement (optionnel) ──
# codex : model_reasoning_effort = low | medium | high | xhigh
#         [Documenté: developers.openai.com/codex/config-reference]
# claude : pas d'équivalent en ligne de commande → ignoré.
# Mapping depuis les niveaux L/M/H déjà exposés par le dashboard (.effort).
engine_effort_flag() {
    local cli="$1" effort="$2"
    [ -z "$effort" ] && return 0
    [ "$cli" != "codex" ] && return 0
    case "$effort" in
        L) printf -- '-c model_reasoning_effort=low' ;;
        M) printf -- '-c model_reasoning_effort=medium' ;;
        H) printf -- '-c model_reasoning_effort=high' ;;
    esac
}

# ── Construction de la commande de lancement ──
# engine_launch_cmd <cli> <profiles_dir> <login_profile> <model> [effort]
# Écrit sur stdout la commande complète à passer à `tmux send-keys`.
# Retourne 1 (et n'écrit rien) si une validation échoue.
engine_launch_cmd() {
    local cli="$1" profiles_dir="$2" login="$3" model="$4" effort="${5:-}"

    engine_is_valid "$cli" || return 1

    if [ -n "$login" ] && [[ ! "$login" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        return 1
    fi
    if [ -n "$model" ] && [[ ! "$model" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
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

    if [ -n "$login" ]; then
        cmd+="$(engine_config_env "$cli")=$profiles_dir/$login "
    fi
    cmd+="$cli $(engine_bypass_flag "$cli")"

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

    printf '%s\n' "$cmd"
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
        echo "  → CODEX_HOME='$codex_home' codex login   (choisir « Sign in with ChatGPT »)" >&2
        return 1
    fi

    # Opt-in explicite : facturation à l'usage assumée.
    [ "${CODEX_ALLOW_API_KEY:-0}" = "1" ] && return 0

    # Tester la clé API EN PREMIER : un diagnostic mixte ne doit pas être pris
    # pour un login ChatGPT au seul motif qu'il mentionne « ChatGPT ».
    if printf '%s' "$status" | grep -qF "$CODEX_AUTH_API_KEY"; then
        echo "Profil '$login' authentifié par CLÉ API → facturation au token, hors forfait." >&2
        echo "  → CODEX_HOME='$codex_home' codex logout && CODEX_HOME='$codex_home' codex login" >&2
        echo "  → puis choisir « Sign in with ChatGPT »" >&2
        echo "  (Pour assumer la facturation à l'usage : CODEX_ALLOW_API_KEY=1)" >&2
        return 1
    fi

    if printf '%s' "$status" | grep -qF "$CODEX_AUTH_CHATGPT"; then
        return 0
    fi

    echo "Profil '$login' : méthode d'authentification inattendue — $status" >&2
    echo "  → CODEX_HOME='$codex_home' codex login   (choisir « Sign in with ChatGPT »)" >&2
    return 1
}
