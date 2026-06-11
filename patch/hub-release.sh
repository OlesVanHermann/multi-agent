#!/bin/bash
# hub-release.sh — Release workflow: test → bump → tag → push
# Usage: ./patch/hub-release.sh [major|minor|patch]
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

# 3. Garde-fou anti-fuite de secrets (D3)
echo -e "${CYAN}[1/6] Checking secrets (D3)...${NC}"
if ./patch/check-secrets.sh; then
    echo -e "${GREEN}Secret check passed.${NC}"
else
    echo -e "${RED}Secret check FAILED. Aborting release.${NC}"
    exit 1
fi
echo ""

# 4. Run tests
echo -e "${CYAN}[2/6] Running tests...${NC}"
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

echo -e "${CYAN}[3/6] Version: ${YELLOW}$CURRENT_TAG${NC} → ${GREEN}$NEW_VERSION${NC}"
echo ""

# 5. Update version in CLAUDE.md
echo -e "${CYAN}[4/6] Updating version in CLAUDE.md...${NC}"
sed -i "s/Multi-Agent System v[0-9]*\.[0-9]*/Multi-Agent System v${MAJOR}.${MINOR}/" CLAUDE.md 2>/dev/null || true
sed -i "s/Multi-Agent System v[0-9]*\.[0-9]*\.[0-9]*/Multi-Agent System v${MAJOR}.${MINOR}.${PATCH_NUM}/" CLAUDE.md 2>/dev/null || true

# Count changes since last tag
COMMIT_COUNT=$(git rev-list --count "${CURRENT_TAG}..HEAD" 2>/dev/null || echo "0")
CHANGES=$(git log --oneline "${CURRENT_TAG}..HEAD" 2>/dev/null | head -10)

# C3 : manifest d'intégrité des fichiers framework (vérifié par upgrade.sh).
# Basé sur les fichiers trackés git → identique au contenu d'un clone frais.
echo -e "${CYAN}Generating patch/checksums.sha256 (C3)...${NC}"
FRAMEWORK_PATHS=(scripts web docs patch setup tests templates examples framework
                 requirements.txt CLAUDE.md README.md LICENSE .gitignore)
# ':!...' = pathspec git d'exclusion (le manifest ne peut pas se contenir lui-même)
git ls-files -z -- "${FRAMEWORK_PATHS[@]}" ':!patch/checksums.sha256' \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > patch/checksums.sha256
git add patch/checksums.sha256

# Commit version bump
git add CLAUDE.md
git commit -m "release: $NEW_VERSION" --allow-empty 2>/dev/null || true
echo ""

# 6. Tag (signé GPG si une clé de signature est configurée — C3)
echo -e "${CYAN}[5/6] Creating tag $NEW_VERSION...${NC}"
TAG_SIGN_FLAG="-a"
if git config --get user.signingkey >/dev/null 2>&1; then
    TAG_SIGN_FLAG="-s"
    echo -e "${GREEN}Signing tag with GPG key $(git config --get user.signingkey)${NC}"
else
    echo -e "${YELLOW}No user.signingkey configured — tag annoté non signé.${NC}"
fi
git tag "$TAG_SIGN_FLAG" "$NEW_VERSION" -m "Version ${NEW_VERSION} - ${COMMIT_COUNT} commits since ${CURRENT_TAG}"
echo ""

# 7. Push to GitHub via orphan commit (single commit, no history)
echo -e "${CYAN}[6/6] Pushing to GitHub (origin) via orphan commit...${NC}"
TREE=$(git write-tree)
ORPHAN=$(git commit-tree "$TREE" -m "release: $NEW_VERSION")
git tag "$TAG_SIGN_FLAG" -f "$NEW_VERSION" "$ORPHAN" -m "Version ${NEW_VERSION} - ${COMMIT_COUNT} commits since ${CURRENT_TAG}"
git push --force origin "$ORPHAN":refs/heads/main
git push --force origin "$NEW_VERSION"
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
