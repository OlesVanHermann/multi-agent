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

# 1. Releases are made from a maintained release line.
CURRENT=$(git branch --show-current)
case "$CURRENT" in
    main) RELEASE_LINE="3.1"; RELEASE_REMOTE_BRANCH="main" ;;
    v3.1) RELEASE_LINE="3.1"; RELEASE_REMOTE_BRANCH="v3.1" ;;
    *)
        echo -e "${RED}Error: releases are allowed from 'main' or 'v3.1' (currently '$CURRENT').${NC}"
        exit 1 ;;
esac

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
if python3 -m pytest tests/ -v 2>&1; then
    echo -e "${GREEN}Tests passed.${NC}"
else
    echo -e "${RED}Tests FAILED. Aborting release.${NC}"
    exit 1
fi
echo ""

# 4. Get current version and bump
CURRENT_TAG=$(git tag --list "v${RELEASE_LINE}.*" --sort=-v:refname | head -1)
if [ -z "$CURRENT_TAG" ]; then
    # A new release line starts at .0 when the default patch bump is used.
    CURRENT_TAG="v${RELEASE_LINE}.-1"
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

# 5. Update version in CLAUDE.md + README.md
echo -e "${CYAN}[4/6] Updating version in CLAUDE.md + README.md...${NC}"
for DOC in CLAUDE.md README.md; do
    sed -i "s/Multi-Agent System v[0-9]*\.[0-9]*/Multi-Agent System v${MAJOR}.${MINOR}/" "$DOC" 2>/dev/null || true
    sed -i "s/Multi-Agent System v[0-9]*\.[0-9]*\.[0-9]*/Multi-Agent System v${MAJOR}.${MINOR}.${PATCH_NUM}/" "$DOC" 2>/dev/null || true
done

# Count changes since last tag
# NB : les tags release sont des commits orphelins → la plage couvre tout
# l'historique. Pas de `| head` ici : sous pipefail, git log tué par SIGPIPE
# (141) avorterait le script en silence — la limite se passe à git (-n 10).
COMMIT_COUNT=$(git rev-list --count "${CURRENT_TAG}..HEAD" 2>/dev/null || echo "0")
CHANGES=$(git log --oneline -n 10 "${CURRENT_TAG}..HEAD" 2>/dev/null || true)

# C3 : manifest d'intégrité des fichiers framework (vérifié par upgrade.sh).
# Basé sur les fichiers trackés git → identique au contenu d'un clone frais.
# Miroir exact de MANIFEST_PATHS dans upgrade.sh — verrouillé par
# tests/test_upgrade_manifest_sync.py, modifier les deux ensemble.
echo -e "${CYAN}Generating patch/checksums.sha256 (C3)...${NC}"
FRAMEWORK_PATHS=(scripts web docs patch setup tests templates examples framework .github bench
                 'login/*/settings.json'
                 prompts/150-create-mono prompts/160-create-x45 prompts/170-create-z21
                 prompts/RULES.md prompts/CONVENTIONS.md prompts/PATHS.md
                 prompts/AGENT.md prompts/CHROME.md
                 prompts/agent_mono.type prompts/agent_x45.type prompts/agent_z21.type
                 prompts/gpt-5-6-luna.model prompts/gpt-5-6-sol.model prompts/gpt-5-6-terra.model
                 'prompts/codex*.login'
                 requirements.txt CLAUDE.md AGENTS.md README.md LICENSE .gitignore)
# ':!...' = pathspec git d'exclusion (le manifest ne peut pas se contenir lui-même)
git ls-files -z -- "${FRAMEWORK_PATHS[@]}" ':!patch/checksums.sha256' \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > patch/checksums.sha256
git add patch/checksums.sha256

# Commit version bump
git add CLAUDE.md README.md
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
git push --force origin "$ORPHAN:refs/heads/$RELEASE_REMOTE_BRANCH"
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
