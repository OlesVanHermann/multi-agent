#!/bin/bash
# create_login.sh - Create Claude Code login profiles for multi-agent
# Usage: source ./scripts/create_login.sh <name> [name2 ...]
#
# Creates for each login:
#   - login/<name>/ directory (CLAUDE_CONFIG_DIR)
#   - prompts/<name>.login file
#   - Alias in ~/.bashrc_claude
#   - Interactive claude auth
#
# Then assign to agents via symlinks:
#   ln -sf claude1a.login default.login   # All agents
#   ln -sf claude2a.login 300.login       # Agent 300 only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PROFILES_DIR="$BASE_DIR/login"
BASHRC_CLAUDE="$HOME/.bashrc_claude"
BASHRC="$HOME/.bashrc"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

# ── Help ──

if [ $# -eq 0 ]; then
    echo "Usage: $0 <profile_name> [profile_name2 ...]"
    echo ""
    echo "Examples:"
    echo "  $0 claude1a                  # Create single profile"
    echo "  $0 claude1a claude1b claude2a  # Create multiple profiles"
    echo ""
    echo "Existing profiles:"
    ls -1 "$PROFILES_DIR" 2>/dev/null | sed 's/^/  /' || echo "  (none)"
    return 1 2>/dev/null || exit 1
fi

# ── Create .bashrc_claude if missing ──

if [ ! -f "$BASHRC_CLAUDE" ]; then
    cat > "$BASHRC_CLAUDE" << BASHRC_EOF
# === Claude Code Multi-Profils ===
# Source this file from .bashrc: [ -f ~/.bashrc_claude ] && source ~/.bashrc_claude

export CLAUDE_PROFILES_DIR="$PROFILES_DIR"

alias claude='claude --dangerously-skip-permissions'

# === Fin Claude Code ===
BASHRC_EOF
    echo -e "${GREEN}[OK]${NC} Created $BASHRC_CLAUDE"
fi

# ── Ensure .bashrc sources .bashrc_claude ──

if ! grep -qF 'bashrc_claude' "$BASHRC" 2>/dev/null; then
    echo '' >> "$BASHRC"
    echo '# Claude Code profiles' >> "$BASHRC"
    echo '[ -f ~/.bashrc_claude ] && source ~/.bashrc_claude' >> "$BASHRC"
    echo -e "${GREEN}[OK]${NC} Added source line to $BASHRC"
fi

# ── Create each profile ──

CREATED_PROFILES=()

for PROFILE in "$@"; do
    echo -e "${BLUE}[INFO]${NC} Profile: $PROFILE"

    # 1. Create profile directory
    mkdir -p "$PROFILES_DIR/$PROFILE"
    echo -e "${GREEN}[OK]${NC}   Directory: $PROFILES_DIR/$PROFILE"

    # 2. Add alias to .bashrc_claude if not present
    ALIAS_NAME="${PROFILE}"
    if grep -qF "alias ${ALIAS_NAME}=" "$BASHRC_CLAUDE" 2>/dev/null; then
        echo -e "${YELLOW}[WARN]${NC} Alias $ALIAS_NAME already in .bashrc_claude"
    else
        # Insert before "# === Fin Claude Code ===" marker
        ALIAS_LINE="alias ${ALIAS_NAME}='CLAUDE_CONFIG_DIR=${PROFILES_DIR}/${PROFILE} claude --dangerously-skip-permissions'"
        TMPFILE=$(mktemp)
        awk -v line="$ALIAS_LINE" '/# === Fin Claude Code ===/ { print line }{ print }' "$BASHRC_CLAUDE" > "$TMPFILE" && mv "$TMPFILE" "$BASHRC_CLAUDE"
        echo -e "${GREEN}[OK]${NC}   Alias: $ALIAS_NAME added to .bashrc_claude"
    fi

    # 3. Create prompts/<name>.login file
    LOGIN_FILE="$BASE_DIR/prompts/${PROFILE}.login"
    if [ -f "$LOGIN_FILE" ]; then
        echo -e "${YELLOW}[WARN]${NC} prompts/${PROFILE}.login already exists"
    else
        echo "$PROFILE" > "$LOGIN_FILE"
        echo -e "${GREEN}[OK]${NC}   Login file: prompts/${PROFILE}.login"
    fi

    CREATED_PROFILES+=("$PROFILE")
    echo ""
done

# ── Source .bashrc_claude ──

source "$BASHRC_CLAUDE" 2>/dev/null || true

# ── Authenticate each profile ──

echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   PROFILES CREATED — AUTHENTICATING${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""

set +e
for PROFILE in "${CREATED_PROFILES[@]}"; do
    echo -e "${BLUE}[AUTH]${NC} Authenticating profile: $PROFILE"
    echo -e "${BLUE}[AUTH]${NC} Once authenticated, type /exit to continue"
    echo ""
    CLAUDE_CONFIG_DIR="$PROFILES_DIR/$PROFILE" claude </dev/tty >/dev/tty 2>&1
    echo ""
    echo -e "${BLUE}[AUTH]${NC} Validating profile: $PROFILE (type /exit when done)"
    echo ""
    CLAUDE_CONFIG_DIR="$PROFILES_DIR/$PROFILE" claude --dangerously-skip-permissions </dev/tty >/dev/tty 2>&1
    echo ""
    echo -e "${GREEN}[OK]${NC} Profile $PROFILE done"
    echo ""
done
set -e

echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   ALL PROFILES READY${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Login directory: $PROFILES_DIR"
echo "  Aliases file:   $BASHRC_CLAUDE"
echo ""
echo "  Login files created in prompts/:"
for PROFILE in "${CREATED_PROFILES[@]}"; do
    echo "    prompts/${PROFILE}.login"
done
echo ""
echo "  Assign to agents via symlinks:"
echo "    cd $BASE_DIR/prompts"
echo "    ln -sf ${1}.login default.login       # All agents → ${1}"
if [ ${#CREATED_PROFILES[@]} -gt 1 ]; then
    echo "    ln -sf ${CREATED_PROFILES[1]}.login 300.login   # Agent 300 → ${CREATED_PROFILES[1]}"
fi
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
# Load aliases in current shell
source "$BASHRC_CLAUDE" 2>/dev/null || true
echo -e "${GREEN}[OK]${NC} Aliases loaded in current shell"
echo ""
