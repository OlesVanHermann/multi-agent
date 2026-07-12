#!/usr/bin/env bash
# G1 — Faux CLI Claude Code pour les tests E2E du bridge (tests/test_e2e_bridge.py).
#
# Tourne dans un pane tmux à la place du vrai `claude` et reproduit les
# rendus terminal que agent.py détecte (markers.yaml) : prompt prêt,
# compaction, erreur API, sondage de session, approbation de plan.
#
# Variables d'environnement :
#   FAKE_CLAUDE_SCENARIO  nominal | compaction | api_error | survey | plan
#   FAKE_CLAUDE_LOG       fichier où chaque ligne reçue est consignée
#   FAKE_CLAUDE_DELAY     délai (s) avant de répondre — laisse au bridge le
#                         temps de capturer sa baseline dans _wait_for_response

SCENARIO="${FAKE_CLAUDE_SCENARIO:-nominal}"
LOG="${FAKE_CLAUDE_LOG:-/dev/null}"
DELAY="${FAKE_CLAUDE_DELAY:-1}"

# Doit contenir STATUS_LINE ('bypass permissions') de markers.yaml,
# sans BUSY_MARKERS ('esc to interrupt').
STATUS_LINE="  bypass permissions on (shift+tab to cycle)"

show_prompt() {
    echo "$STATUS_LINE"
    printf '❯ '
}

clear_pane() {
    # capture-pane -S -200 inclut le scrollback : sans purge, les anciens
    # textes (survey, API Error) seraient re-détectés indéfiniment.
    printf '\033[2J\033[H'
    tmux clear-history 2>/dev/null || true
}

count=0
show_prompt
while IFS= read -r line; do
    [ -z "$line" ] && continue
    count=$((count + 1))
    printf '%s\n' "$line" >> "$LOG"
    sleep "$DELAY"

    case "$SCENARIO" in
        nominal)
            echo "RESPONSE_OK: traite [$line]"
            ;;
        compaction)
            if [ "$count" -eq 1 ]; then
                echo "Conversation compacted · ctrl+o for history"
            else
                echo "RESPONSE_OK: traite [$line]"
            fi
            ;;
        api_error)
            if [ "$count" -eq 1 ]; then
                echo 'API Error: 401 {"type":"error"} (fake)'
            else
                clear_pane
                echo "RETRY_OK: traite [$line]"
            fi
            ;;
        survey)
            if [ "$count" -eq 1 ]; then
                echo "How is Claude doing this session?"
                echo "  1: Bad  2: Fine  3: Great"
            else
                # le bridge a envoyé "0" pour rejeter le sondage
                clear_pane
                echo "SURVEY_DISMISSED_OK"
            fi
            ;;
        plan)
            if [ "$count" -eq 1 ]; then
                echo "Would you like to proceed?"
                echo "  1. Yes"
                echo "  2. No"
                # ni status line ni marqueur : le bridge reste en waiting_approval
                continue
            else
                clear_pane
                echo "PLAN_APPROVED_OK"
            fi
            ;;
        *)
            echo "RESPONSE_OK: traite [$line]"
            ;;
    esac
    show_prompt
done
