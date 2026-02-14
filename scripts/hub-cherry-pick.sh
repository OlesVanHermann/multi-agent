#!/bin/bash
# hub-cherry-pick.sh — Cherry-pick commits from a patch branch
# Usage: ./scripts/hub-cherry-pick.sh <branch> [commit_hash...]
#
# Examples:
#   ./scripts/hub-cherry-pick.sh hub/patch/onlyoffice/fix-timeout        # pick all
#   ./scripts/hub-cherry-pick.sh hub/patch/onlyoffice/fix-timeout abc123  # pick one
#   ./scripts/hub-cherry-pick.sh hub/patch/onlyoffice/fix-timeout abc def # pick multiple

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

if [ $# -lt 1 ]; then
    echo -e "${BOLD}Usage:${NC} $0 <branch> [commit_hash...]"
    echo ""
    echo "  branch       Remote branch (e.g. hub/patch/projet/fix-xxx)"
    echo "  commit_hash  Optional: specific commit(s) to pick. If omitted, picks all."
    echo ""
    echo -e "${BOLD}Examples:${NC}"
    echo "  $0 hub/patch/onlyoffice/fix-timeout         # all commits"
    echo "  $0 hub/patch/onlyoffice/fix-timeout abc123   # one commit"
    exit 1
fi

BRANCH="$1"
shift
SPECIFIC_COMMITS=("$@")

# Fetch latest
git fetch hub --quiet 2>/dev/null

# Verify branch exists
if ! git rev-parse --verify "$BRANCH" &>/dev/null; then
    echo -e "${RED}Error: Branch '$BRANCH' not found.${NC}"
    echo "Available patch branches:"
    git branch -r --list 'hub/patch/*' | sed 's/^ */  /'
    exit 1
fi

# Show commits in the branch (ahead of main)
echo -e "${BOLD}=== Commits in $BRANCH ===${NC}"
echo ""
git log --oneline --reverse main.."$BRANCH"
echo ""

COMMITS_AHEAD=$(git rev-list --count main.."$BRANCH")

if [ "$COMMITS_AHEAD" -eq 0 ]; then
    echo -e "${GREEN}All commits already in main. Nothing to cherry-pick.${NC}"
    exit 0
fi

# Determine which commits to pick
if [ ${#SPECIFIC_COMMITS[@]} -gt 0 ]; then
    PICKS=("${SPECIFIC_COMMITS[@]}")
    echo -e "${CYAN}Cherry-picking ${#PICKS[@]} specific commit(s)...${NC}"
else
    # All commits from the branch not in main, in chronological order
    mapfile -t PICKS < <(git rev-list --reverse main.."$BRANCH")
    echo -e "${CYAN}Cherry-picking all $COMMITS_AHEAD commit(s)...${NC}"
fi

echo ""

SUCCESS=0
FAILED=0

for commit in "${PICKS[@]}"; do
    msg=$(git log -1 --format='%h %s' "$commit" 2>/dev/null || echo "$commit")

    if git cherry-pick "$commit" --no-edit 2>/dev/null; then
        echo -e "  ${GREEN}OK${NC}  $msg"
        SUCCESS=$((SUCCESS + 1))
    else
        echo -e "  ${RED}FAIL${NC} $msg"
        echo -e "  ${YELLOW}Conflict detected. Resolve manually then: git cherry-pick --continue${NC}"
        FAILED=$((FAILED + 1))
        break
    fi
done

echo ""
echo -e "${BOLD}Result: ${GREEN}$SUCCESS picked${NC}, ${RED}$FAILED failed${NC}"

if [ $FAILED -eq 0 ] && [ $SUCCESS -gt 0 ]; then
    echo ""
    echo -e "${GREEN}All commits applied successfully.${NC}"
    echo -e "Next: ${CYAN}python -m pytest tests/ -v${NC} then ${CYAN}./scripts/hub-release.sh${NC}"

    # Extract project name for cleanup suggestion
    PROJECT_BRANCH=$(echo "$BRANCH" | sed 's|hub/||')
    echo -e "Cleanup: ${CYAN}git push hub --delete $PROJECT_BRANCH${NC}"
fi
