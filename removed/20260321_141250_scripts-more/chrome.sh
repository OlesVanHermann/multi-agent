#!/bin/bash
# =============================================================================
# chrome.sh — Gestion du Chrome partagé pour le Multi-Agent System
# =============================================================================
#
# Ce script gère le cycle de vie d'une instance Chrome partagée entre tous
# les agents du système. Chrome est lancé normalement et l'extension CDP
# Bridge (Native Messaging Host) expose un serveur HTTP sur le port 9222,
# permettant aux agents de contrôler le navigateur via chrome-bridge.py.
#
# ARCHITECTURE:
#   - UN SEUL Chrome pour tous les agents (économie de mémoire)
#   - Chaque agent a son propre onglet isolé (via Redis: ma:chrome:tab:{id})
#   - Le mapping agent→onglet est géré par chrome-bridge.py et crawl*.py
#   - L'extension CDP Bridge fournit les capacités CDP depuis l'intérieur
#     de Chrome (pas détecté comme automation par Google)
#
# SÉCURITÉ:
#   - Chrome ne doit JAMAIS être arrêté automatiquement
#   - Les sessions utilisateur (cookies, auth) seraient perdues
#   - Seul le start est autorisé, le stop est bloqué volontairement
#
# USAGE:
#   ./chrome.sh start    # Lancer Chrome
#   ./chrome.sh stop     # INTERDIT — affiche un message d'erreur
#   ./chrome.sh status   # Vérifier si Chrome est actif + infos version
#   ./chrome.sh          # Équivalent à status (commande par défaut)
#
# PRÉREQUIS:
#   - Google Chrome installé (chemin macOS par défaut)
#   - Extension CDP Bridge installée dans Chrome
#   - Native Messaging Host installé (./install.sh)
#
# =============================================================================

# --- Configuration ---
# Port du bridge HTTP (Native Messaging Host) — tous les agents se connectent ici
CHROME_PORT=9222

# Répertoire de profil Chrome dédié au multi-agent
# Séparé du profil utilisateur pour éviter les conflits
CHROME_USER_DATA="$HOME/.chrome-multi-agent"

# Chemin de l'exécutable Chrome (macOS)
# Sur Linux, utiliser: /usr/bin/google-chrome ou /usr/bin/chromium-browser
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


# =============================================================================
# start() — Lance Chrome (sans --remote-debugging-port)
# =============================================================================
# Vérifie d'abord si le bridge est déjà actif pour éviter les doublons.
# Lance Chrome en arrière-plan avec:
#   --user-data-dir         : profil Chrome isolé (pas le profil perso)
#   --no-first-run          : désactive l'assistant de première utilisation
#   --no-default-browser    : désactive la popup "navigateur par défaut"
#
# NOTE: PAS de --remote-debugging-port ! Le bridge Native Messaging Host
# fournit les capacités CDP via l'extension Chrome, ce qui évite la
# détection d'automation par Google.
#
# Attend jusqu'à 15 secondes que le bridge soit prêt (poll toutes les 0.5s)
# =============================================================================
start() {
    # Vérifier si le bridge est déjà actif en testant l'endpoint /health
    if curl -s "http://127.0.0.1:$CHROME_PORT/health" > /dev/null 2>&1; then
        echo "✓ Chrome + bridge déjà actif sur port $CHROME_PORT"
        return 0
    fi

    echo "Lancement Chrome..."

    # Lancer Chrome en arrière-plan (PAS de --remote-debugging-port)
    # Le bridge CDP est fourni par l'extension + Native Messaging Host
    "$CHROME_PATH" \
        --user-data-dir="$CHROME_USER_DATA" \
        --no-first-run \
        --no-default-browser-check &

    # Boucle d'attente: poll le bridge jusqu'à ce qu'il réponde
    # Maximum 30 tentatives × 0.5s = 15 secondes de timeout
    for i in {1..30}; do
        sleep 0.5
        if curl -s "http://127.0.0.1:$CHROME_PORT/health" > /dev/null 2>&1; then
            echo "✓ Chrome + bridge prêt sur port $CHROME_PORT"
            echo "  Profile: $CHROME_USER_DATA"
            return 0
        fi
    done

    # Si on arrive ici, Chrome/bridge n'a pas démarré dans les 15 secondes
    echo "✗ Échec du lancement Chrome ou bridge non actif"
    echo "  Vérifier que l'extension CDP Bridge est installée"
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
# Pour arrêter Chrome manuellement: kill $(pgrep -f "Google Chrome")
# =============================================================================
stop() {
    echo "⛔ INTERDIT: Chrome ne doit JAMAIS être arrêté"
    echo "   Les sessions utilisateur seraient perdues."
    exit 1
}


# =============================================================================
# status() — Affiche l'état de Chrome + bridge
# =============================================================================
# Interroge l'endpoint /health du bridge pour récupérer:
#   - L'état de la connexion extension
#   - Le nombre d'onglets actifs (type "page" uniquement)
#   - Le chemin du profil utilisé
#
# Code de sortie: 0 si Chrome + bridge actifs, 1 sinon
# =============================================================================
status() {
    if curl -s "http://127.0.0.1:$CHROME_PORT/health" > /dev/null 2>&1; then
        # Bridge répond — extraire les infos
        EXTENSION=$(curl -s "http://127.0.0.1:$CHROME_PORT/health" | python3 -c "import json,sys; print(json.load(sys.stdin).get('extensionConnected','?'))" 2>/dev/null)
        TABS=$(curl -s "http://127.0.0.1:$CHROME_PORT/json" | python3 -c "import json,sys; tabs=[t for t in json.load(sys.stdin) if t.get('type')=='page']; print(len(tabs))" 2>/dev/null)
        echo "✓ Chrome + bridge actif"
        echo "  Extension: $EXTENSION"
        echo "  Port: $CHROME_PORT"
        echo "  Profile: $CHROME_USER_DATA"
        echo "  Onglets: $TABS"
    else
        echo "✗ Chrome/bridge non actif sur port $CHROME_PORT"
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
