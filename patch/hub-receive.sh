#!/bin/bash
# hub-receive.sh — List incoming patches from project machines
# Usage: ./patch/hub-receive.sh [--log]

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}=== Hub Patches ===${NC}"
echo ""

# Fetch latest from bare repo
git fetch hub --prune --quiet 2>/dev/null

# List all patch branches
PATCHES=$(git branch -r --list 'hub/patch/*' 2>/dev/null | sed 's/^ *//')

if [ -z "$PATCHES" ]; then
    echo -e "${GREEN}No pending patches.${NC}"

    # Show push log if --log flag
    if [ "${1:-}" = "--log" ] && [ -f /home/ubuntu/multi-agent.git/push.log ]; then
        echo ""
        echo -e "${BOLD}=== Recent Push Log ===${NC}"
        tail -30 /home/ubuntu/multi-agent.git/push.log
    fi
    exit 0
fi

# Group by project
declare -A PROJECTS
for branch in $PATCHES; do
    # Extract project name: hub/patch/projet-a/fix-xxx → projet-a
    project=$(echo "$branch" | sed 's|hub/patch/||' | cut -d'/' -f1)
    PROJECTS[$project]+="$branch "
done

TOTAL=0
for project in $(echo "${!PROJECTS[@]}" | tr ' ' '\n' | sort); do
    branches="${PROJECTS[$project]}"
    echo -e "${CYAN}${BOLD}[$project]${NC}"

    for branch in $branches; do
        desc=$(echo "$branch" | sed "s|hub/patch/$project/||")

        # Count commits ahead of main
        ahead=$(git rev-list --count main.."$branch" 2>/dev/null || echo "?")

        # Last commit info
        last=$(git log -1 --format='%h %s (%cr)' "$branch" 2>/dev/null || echo "?")

        # Signaux d'alerte (leçon 2026-07-28 : une branche projet complète
        # de 842 commits / 872 Mo avec credentials a été poussée sur le hub)
        warn=""
        if ! git merge-base main "$branch" >/dev/null 2>&1; then
            warn=" ${RED}${BOLD}!! SANS ANCÊTRE COMMUN avec main — ne jamais merger ni cherry-picker la branche entière ; exiger un re-push rebasé${NC}"
        elif [ "$ahead" != "?" ] && [ "$ahead" -gt 50 ]; then
            warn=" ${RED}!! ${ahead} commits d'avance — probable historique projet complet, inspecter avant tout pick${NC}"
        fi

        echo -e "  ${YELLOW}$desc${NC} [${GREEN}+${ahead}${NC}] $last$warn"
        TOTAL=$((TOTAL + 1))
    done
    echo ""
done

echo -e "${BOLD}Total: $TOTAL patch branch(es)${NC}"
echo ""
echo -e "Cherry-pick:  ${CYAN}./patch/hub-cherry-pick.sh hub/patch/<project>/<desc>${NC}"
echo -e "View commits: ${CYAN}git log main..hub/patch/<project>/<desc>${NC}"

# Show push log if --log flag
if [ "${1:-}" = "--log" ] && [ -f /home/ubuntu/multi-agent.git/push.log ]; then
    echo ""
    echo -e "${BOLD}=== Recent Push Log ===${NC}"
    tail -30 /home/ubuntu/multi-agent.git/push.log
fi
