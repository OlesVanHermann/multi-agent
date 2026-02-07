#!/bin/bash
# sync-to-git.sh — Sync framework changes from /multi-agent/ to /multi-agent-git/ and push to hub
#
# Usage: ./sync-to-git.sh "description of changes"
#        ./sync-to-git.sh "add-ma-prefix"
#        ./sync-to-git.sh "fix-timeout" --dry-run
#
# Setup (once per Mac):
#   git clone git@github.com:OlesVanHermann/multi-agent.git /path/to/multi-agent-git
#   git -C /path/to/multi-agent-git remote add hub ubuntu@mx9.di2amp.com:/home/ubuntu/multi-agent.git
#
# Config: set these env vars or edit defaults below

set -euo pipefail

# === CONFIG ===
# Source: your working multi-agent (with project modifications)
MA_SRC="${MA_SRC:-$HOME/multi-agent}"
# Destination: clean git repo for pushing patches
MA_GIT="${MA_GIT:-$HOME/multi-agent-git}"
# Hub remote name in the git repo
HUB_REMOTE="${HUB_REMOTE:-hub}"

# Detect project name from project-config.md or directory
if [ -f "$MA_SRC/project-config.md" ]; then
    PROJECT_NAME=$(grep '^PROJECT_NAME=' "$MA_SRC/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
PROJECT_NAME="${PROJECT_NAME:-$(basename "$(realpath "$MA_SRC/project" 2>/dev/null || echo "unknown")")}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# === ARGS ===
DESCRIPTION="${1:-}"
DRY_RUN=false
[[ "${2:-}" == "--dry-run" || "${1:-}" == "--dry-run" ]] && DRY_RUN=true
[[ "${1:-}" == "--dry-run" ]] && DESCRIPTION=""

if [ -z "$DESCRIPTION" ]; then
    echo "Usage: $0 <description> [--dry-run]"
    echo ""
    echo "  description   Short slug for the patch (e.g. 'fix-timeout', 'add-prefix')"
    echo "  --dry-run     Show what would be synced without doing it"
    echo ""
    echo "Config (env vars):"
    echo "  MA_SRC=$MA_SRC"
    echo "  MA_GIT=$MA_GIT"
    echo "  HUB_REMOTE=$HUB_REMOTE"
    echo "  PROJECT_NAME=$PROJECT_NAME"
    exit 1
fi

BRANCH="patch/${PROJECT_NAME}/${DESCRIPTION}"

echo -e "${BOLD}=== sync-to-git ===${NC}"
echo -e "  Source:  ${CYAN}$MA_SRC${NC}"
echo -e "  Dest:    ${CYAN}$MA_GIT${NC}"
echo -e "  Project: ${CYAN}$PROJECT_NAME${NC}"
echo -e "  Branch:  ${CYAN}$BRANCH${NC}"
echo ""

# === VALIDATE ===
if [ ! -d "$MA_SRC/core" ]; then
    echo -e "${RED}Error: $MA_SRC doesn't look like a multi-agent directory (no core/)${NC}"
    exit 1
fi

if [ ! -d "$MA_GIT/.git" ]; then
    echo -e "${RED}Error: $MA_GIT is not a git repository${NC}"
    echo "Run: git clone git@github.com:OlesVanHermann/multi-agent.git $MA_GIT"
    exit 1
fi

# === FRAMEWORK FILES TO SYNC ===
# These are the framework files (not project-specific)
INCLUDES=(
    "core/"
    "scripts/"
    "docs/"
    "tests/"
    "web/"
    "upgrades/"
    "infrastructure/"
    "templates/"
    "examples/"
    "requirements.txt"
    "CLAUDE.md"
    "README.md"
)

# === SYNC ===
echo -e "${CYAN}[1/4] Syncing framework files...${NC}"

RSYNC_ARGS=(
    -av
    --delete
    --checksum
)

# Build include/exclude for rsync
for inc in "${INCLUDES[@]}"; do
    RSYNC_ARGS+=(--include="$inc" --include="${inc}**")
done

# Exclude everything else at root level
RSYNC_ARGS+=(
    --exclude="prompts/"
    --exclude="pool-requests/"
    --exclude="project/"
    --exclude="project-config.md"
    --exclude="logs/"
    --exclude="sessions/"
    --exclude="removed/"
    --exclude=".git/"
    --exclude="__pycache__/"
    --exclude=".pytest_cache/"
    --exclude="*.pyc"
    --exclude=".claude/"
)

if $DRY_RUN; then
    echo -e "${YELLOW}[DRY RUN] Would sync:${NC}"
    rsync "${RSYNC_ARGS[@]}" --dry-run "$MA_SRC/" "$MA_GIT/" 2>&1 | grep -v '/$' | head -40
    echo ""
    echo -e "${YELLOW}[DRY RUN] Would create branch: $BRANCH${NC}"
    exit 0
fi

rsync "${RSYNC_ARGS[@]}" "$MA_SRC/" "$MA_GIT/" 2>&1 | tail -5
echo ""

# === GIT ===
cd "$MA_GIT"

echo -e "${CYAN}[2/4] Creating branch $BRANCH...${NC}"
# Start from latest main
git checkout main --quiet 2>/dev/null || true
git pull "$HUB_REMOTE" main --quiet 2>/dev/null || true
git checkout -B "$BRANCH" main --quiet

echo -e "${CYAN}[3/4] Committing changes...${NC}"
git add -A

# Check if there are actual changes
if git diff --cached --quiet; then
    echo -e "${YELLOW}No changes to commit. Framework is already in sync.${NC}"
    git checkout main --quiet
    exit 0
fi

# Show what changed
echo ""
git diff --cached --stat
echo ""

git commit -m "patch($PROJECT_NAME): $DESCRIPTION

Synced from $MA_SRC
$(date -Iseconds)"

echo ""
echo -e "${CYAN}[4/4] Pushing to hub...${NC}"
git push "$HUB_REMOTE" "$BRANCH" --force

echo ""
echo -e "${GREEN}${BOLD}=== Done ===${NC}"
echo -e "  Branch: ${GREEN}$BRANCH${NC}"
echo -e "  Commits:"
git log --oneline main.."$BRANCH" | sed 's/^/    /'
echo ""
echo -e "On mx9, inception will process this patch automatically."
echo -e "Or manually: ${CYAN}./scripts/hub-cherry-pick.sh $BRANCH${NC}"

# Return to main
git checkout main --quiet
