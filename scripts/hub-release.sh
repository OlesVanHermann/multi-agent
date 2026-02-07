#!/bin/bash
# hub-release.sh — Release workflow: test → bump → tag → push
# Usage: ./scripts/hub-release.sh [major|minor|patch]
#        Default: patch

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

BUMP_TYPE="${1:-patch}"

echo -e "${BOLD}=== Multi-Agent Release ===${NC}"
echo ""

# 1. Check we're on main
CURRENT=$(git branch --show-current)
if [ "$CURRENT" != "main" ]; then
    echo -e "${RED}Error: Must be on 'main' branch (currently on '$CURRENT').${NC}"
    exit 1
fi

# 2. Check clean working tree
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${RED}Error: Working tree not clean. Commit or stash changes first.${NC}"
    git status --short
    exit 1
fi

# 3. Run tests
echo -e "${CYAN}[1/5] Running tests...${NC}"
if python -m pytest tests/ -v 2>&1; then
    echo -e "${GREEN}Tests passed.${NC}"
else
    echo -e "${RED}Tests FAILED. Aborting release.${NC}"
    exit 1
fi
echo ""

# 4. Get current version and bump
CURRENT_TAG=$(git tag --sort=-v:refname | head -1)
if [ -z "$CURRENT_TAG" ]; then
    CURRENT_TAG="v0.0.0"
fi

# Parse version (strip 'v' prefix)
VERSION="${CURRENT_TAG#v}"
IFS='.' read -r MAJOR MINOR PATCH_NUM <<< "$VERSION"

case "$BUMP_TYPE" in
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH_NUM=0
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH_NUM=0
        ;;
    patch)
        PATCH_NUM=$((PATCH_NUM + 1))
        ;;
    *)
        echo -e "${RED}Unknown bump type: $BUMP_TYPE (use major|minor|patch)${NC}"
        exit 1
        ;;
esac

NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH_NUM}"

echo -e "${CYAN}[2/5] Version: ${YELLOW}$CURRENT_TAG${NC} → ${GREEN}$NEW_VERSION${NC}"
echo ""

# 5. Update version in CLAUDE.md
echo -e "${CYAN}[3/5] Updating version in CLAUDE.md...${NC}"
sed -i "s/Multi-Agent System v[0-9]*\.[0-9]*/Multi-Agent System v${MAJOR}.${MINOR}/" CLAUDE.md 2>/dev/null || true
sed -i "s/Multi-Agent System v[0-9]*\.[0-9]*\.[0-9]*/Multi-Agent System v${MAJOR}.${MINOR}.${PATCH_NUM}/" CLAUDE.md 2>/dev/null || true

# Count changes since last tag
COMMIT_COUNT=$(git rev-list --count "${CURRENT_TAG}..HEAD" 2>/dev/null || echo "0")
CHANGES=$(git log --oneline "${CURRENT_TAG}..HEAD" 2>/dev/null | head -10)

# Commit version bump
git add CLAUDE.md
git commit -m "release: $NEW_VERSION" --allow-empty 2>/dev/null || true
echo ""

# 6. Tag
echo -e "${CYAN}[4/5] Creating tag $NEW_VERSION...${NC}"
git tag -a "$NEW_VERSION" -m "Version ${NEW_VERSION} - ${COMMIT_COUNT} commits since ${CURRENT_TAG}"
echo ""

# 7. Push to GitHub
echo -e "${CYAN}[5/5] Pushing to GitHub (origin)...${NC}"
git push origin main --tags
echo ""

# Summary
echo -e "${GREEN}${BOLD}=== Release $NEW_VERSION Complete ===${NC}"
echo ""
echo -e "Tag:     ${GREEN}$NEW_VERSION${NC}"
echo -e "Commits: ${CYAN}$COMMIT_COUNT${NC} since $CURRENT_TAG"
echo ""
if [ -n "$CHANGES" ]; then
    echo -e "${BOLD}Changes:${NC}"
    echo "$CHANGES" | sed 's/^/  /'
    echo ""
fi

echo -e "${BOLD}Update projects:${NC}"
echo -e "  ${CYAN}ssh user@machine 'cd /path/multi-agent && ./upgrade.sh'${NC}"
echo ""
echo -e "Or manual:"
echo -e "  ${CYAN}git remote add hub ubuntu@mx9.di2amp.com:/home/ubuntu/multi-agent.git${NC}"
echo -e "  ${CYAN}git fetch hub && git merge hub/main${NC}"
