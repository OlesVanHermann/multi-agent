#!/bin/bash
# =============================================================================
# chrome.sh — Gestion du Chrome partagé pour le Multi-Agent System
# =============================================================================
#
# Ce script gère le cycle de vie d'une instance Chrome partagée entre tous
# les agents du système. Chrome est lancé avec le protocole CDP (Chrome
# DevTools Protocol) activé sur le port 9222, ce qui permet aux agents
# de contrôler le navigateur via WebSocket.
#
# ARCHITECTURE:
#   - UN SEUL Chrome pour tous les agents (économie de mémoire)
#   - Chaque agent a son propre onglet isolé (via Redis: ma:chrome:tab:{id})
#   - Le mapping agent→onglet est géré par chrome-shared.py et crawl.py
#
# SÉCURITÉ:
#   - Chrome ne doit JAMAIS être arrêté automatiquement
#   - Les sessions utilisateur (cookies, auth) seraient perdues
#   - Seul le start est autorisé, le stop est bloqué volontairement
#
# USAGE:
#   ./chrome.sh start    # Lancer Chrome avec CDP sur port 9222
#   ./chrome.sh stop     # INTERDIT — affiche un message d'erreur
#   ./chrome.sh status   # Vérifier si Chrome est actif + infos version
#   ./chrome.sh          # Équivalent à status (commande par défaut)
#
# PRÉREQUIS:
#   - Google Chrome installé (chemin macOS par défaut)
#   - Port 9222 libre (pas d'autre instance Chrome en debug)
#
# =============================================================================

# --- Configuration ---
# Port CDP (Chrome DevTools Protocol) — tous les agents se connectent ici
CHROME_PORT=9222

# Répertoire de profil Chrome dédié au multi-agent
# Séparé du profil utilisateur pour éviter les conflits
CHROME_USER_DATA="$HOME/.chrome-multi-agent"

# Chemin de l'exécutable Chrome (macOS)
# Sur Linux, utiliser: /usr/bin/google-chrome ou /usr/bin/chromium-browser
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


# =============================================================================
# start() — Lance Chrome avec CDP activé
# =============================================================================
# Vérifie d'abord si Chrome est déjà actif pour éviter les doublons.
# Lance Chrome en arrière-plan avec:
#   --remote-debugging-port : active CDP sur le port spécifié
#   --user-data-dir         : profil Chrome isolé (pas le profil perso)
#   --remote-allow-origins  : autorise les connexions WebSocket de toute origine
#   --no-first-run          : désactive l'assistant de première utilisation
#   --no-default-browser    : désactive la popup "navigateur par défaut"
#
# Attend jusqu'à 15 secondes que Chrome soit prêt (poll toutes les 0.5s)
# =============================================================================
start() {
    # Vérifier si Chrome est déjà lancé en testant l'endpoint CDP /json/version
    if curl -s "http://127.0.0.1:$CHROME_PORT/json/version" > /dev/null 2>&1; then
        echo "✓ Chrome déjà actif sur port $CHROME_PORT"
        return 0
    fi

    echo "Lancement Chrome sur port $CHROME_PORT..."

    # Lancer Chrome en arrière-plan avec le protocole CDP activé
    "$CHROME_PATH" \
        --remote-debugging-port=$CHROME_PORT \
        --user-data-dir="$CHROME_USER_DATA" \
        --remote-allow-origins='*' \
        --no-first-run \
        --no-default-browser-check &

    # Boucle d'attente: poll l'endpoint CDP jusqu'à ce que Chrome réponde
    # Maximum 30 tentatives × 0.5s = 15 secondes de timeout
    for i in {1..30}; do
        sleep 0.5
        if curl -s "http://127.0.0.1:$CHROME_PORT/json/version" > /dev/null 2>&1; then
            echo "✓ Chrome prêt sur port $CHROME_PORT"
            echo "  Profile: $CHROME_USER_DATA"
            return 0
        fi
    done

    # Si on arrive ici, Chrome n'a pas démarré dans les 15 secondes
    echo "✗ Échec du lancement Chrome"
    return 1
}


# =============================================================================
# stop() — INTERDIT: Chrome ne doit jamais être arrêté
# =============================================================================
# Cette commande est volontairement bloquée pour protéger:
#   - Les sessions authentifiées des utilisateurs
#   - Les cookies et tokens d'authentification
#   - Les onglets ouverts par les agents en cours de travail
#
# Pour arrêter Chrome manuellement: kill $(pgrep -f "chrome.*9222")
# =============================================================================
stop() {
    echo "⛔ INTERDIT: Chrome ne doit JAMAIS être arrêté"
    echo "   Les sessions utilisateur seraient perdues."
    exit 1
}


# =============================================================================
# status() — Affiche l'état de Chrome
# =============================================================================
# Interroge l'endpoint CDP /json/version pour récupérer:
#   - La version du navigateur
#   - Le nombre d'onglets actifs (type "page" uniquement)
#   - Le chemin du profil utilisé
#
# Code de sortie: 0 si Chrome actif, 1 sinon
# =============================================================================
status() {
    if curl -s "http://127.0.0.1:$CHROME_PORT/json/version" > /dev/null 2>&1; then
        # Chrome répond — extraire les infos via Python (parse JSON)
        VERSION=$(curl -s "http://127.0.0.1:$CHROME_PORT/json/version" | python3 -c "import json,sys; print(json.load(sys.stdin)['Browser'])" 2>/dev/null)
        # Compter uniquement les onglets de type "page" (exclut les devtools, extensions, etc.)
        TABS=$(curl -s "http://127.0.0.1:$CHROME_PORT/json" | python3 -c "import json,sys; tabs=[t for t in json.load(sys.stdin) if t.get('type')=='page']; print(len(tabs))" 2>/dev/null)
        echo "✓ Chrome actif"
        echo "  Version: $VERSION"
        echo "  Port: $CHROME_PORT"
        echo "  Profile: $CHROME_USER_DATA"
        echo "  Onglets: $TABS"
    else
        echo "✗ Chrome non actif sur port $CHROME_PORT"
        return 1
    fi
}


# =============================================================================
# Point d'entrée — dispatch vers start/stop/status
# =============================================================================
# Si aucun argument fourni, la commande par défaut est "status"
# =============================================================================
case "${1:-status}" in
    start)  start ;;
    stop)   stop ;;
    status) status ;;
    *)
        echo "Usage: $0 [start|stop|status]"
        exit 1
        ;;
esac
