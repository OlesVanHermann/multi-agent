#!/bin/bash
#
# Chrome partagé pour tous les agents
# Usage: ./chrome.sh [start|stop|status]
#

CHROME_PORT=9222
CHROME_USER_DATA="$HOME/.chrome-multi-agent"
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

start() {
    # Vérifier si déjà lancé
    if curl -s "http://127.0.0.1:$CHROME_PORT/json/version" > /dev/null 2>&1; then
        echo "✓ Chrome déjà actif sur port $CHROME_PORT"
        return 0
    fi

    echo "Lancement Chrome sur port $CHROME_PORT..."

    "$CHROME_PATH" \
        --remote-debugging-port=$CHROME_PORT \
        --user-data-dir="$CHROME_USER_DATA" \
        --remote-allow-origins='*' \
        --no-first-run \
        --no-default-browser-check &

    # Attendre que Chrome soit prêt
    for i in {1..30}; do
        sleep 0.5
        if curl -s "http://127.0.0.1:$CHROME_PORT/json/version" > /dev/null 2>&1; then
            echo "✓ Chrome prêt sur port $CHROME_PORT"
            echo "  Profile: $CHROME_USER_DATA"
            return 0
        fi
    done

    echo "✗ Échec du lancement Chrome"
    return 1
}

stop() {
    echo "⛔ INTERDIT: Chrome ne doit JAMAIS être arrêté"
    echo "   Les sessions utilisateur seraient perdues."
    exit 1
}

status() {
    if curl -s "http://127.0.0.1:$CHROME_PORT/json/version" > /dev/null 2>&1; then
        VERSION=$(curl -s "http://127.0.0.1:$CHROME_PORT/json/version" | python3 -c "import json,sys; print(json.load(sys.stdin)['Browser'])" 2>/dev/null)
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

case "${1:-status}" in
    start)  start ;;
    stop)   stop ;;
    status) status ;;
    *)
        echo "Usage: $0 [start|stop|status]"
        exit 1
        ;;
esac
