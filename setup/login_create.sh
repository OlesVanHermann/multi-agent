#!/bin/bash
# login_create.sh - Create CLI login profiles for multi-agent (E1 : claude | codex)
# Usage: source ./setup/login_create.sh <name> [name2 ...]
#
# Le MOTEUR est porté par le préfixe du nom de profil :
#   claude1a → Claude Code (CLAUDE_CONFIG_DIR, `claude`)
#   codex1a  → OpenAI Codex CLI (CODEX_HOME, `codex`)
#
# Creates for each login:
#   - login/<name>/ directory (CLAUDE_CONFIG_DIR ou CODEX_HOME selon le moteur)
#   - prompts/<name>.login file
#   - Alias in ~/.bashrc_claude
#   - Interactive auth (`claude` ou `codex login`)
#
# Then assign to agents via symlinks:
#   ln -sf claude1a.login default.login   # All agents
# Le slot claude1a est automatiquement résolu vers codex1a avec un modèle gpt-*.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$BASE_DIR/scripts/engines.sh"

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
    echo "  $0 claude1a                    # Profil Claude Code"
    echo "  $0 codex1a                     # Profil OpenAI Codex CLI"
    echo "  $0 claude1a claude1b codex1a   # Plusieurs profils"
    echo ""
    echo "Le moteur est déduit du préfixe : ${ENGINES[*]}"
    echo ""
    echo "Existing profiles:"
    ls -1 "$PROFILES_DIR" 2>/dev/null | sed 's/^/  /' || echo "  (none)"
    return 1 2>/dev/null || exit 1
fi

# ── Create .bashrc_claude if missing ──

if [ ! -f "$BASHRC_CLAUDE" ]; then
    {
        echo "# === Multi-Agent : profils CLI (${ENGINES[*]}) ==="
        echo "# Source this file from .bashrc: [ -f ~/.bashrc_claude ] && source ~/.bashrc_claude"
        echo ""
        echo "export CLAUDE_PROFILES_DIR=\"$PROFILES_DIR\""
        echo ""
        # E1 : un alias « nu » par moteur, généré depuis engines.sh
        for cli in "${ENGINES[@]}"; do
            echo "alias ${cli}='$(engine_launch_cmd "$cli" "$PROFILES_DIR" "" "")'"
        done
        echo ""
        echo "# === Fin Multi-Agent ==="
    } > "$BASHRC_CLAUDE"
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
    # E1 : moteur déduit du préfixe du nom de profil — refus si indéterminable,
    # sinon on créerait un répertoire de profil inutilisable par agent.sh.
    if ! PROFILE_CLI=$(engine_from_profile "$PROFILE"); then
        echo -e "${RED}[ERROR]${NC} Profil '$PROFILE' : moteur indéterminable."
        echo -e "         Préfixe attendu : ${ENGINES[*]} (ex. claude1a, codex2b)"
        continue
    fi
    if ! engine_profile_is_valid "$PROFILE"; then
        echo -e "${RED}[ERROR]${NC} Profil '$PROFILE' : format invalide (<moteur><chiffre><lettre>)"
        continue
    fi
    echo -e "${BLUE}[INFO]${NC} Profile: $PROFILE (moteur: $PROFILE_CLI)"

    # 1. Create profile directory
    mkdir -p "$PROFILES_DIR/$PROFILE"
    echo -e "${GREEN}[OK]${NC}   Directory: $PROFILES_DIR/$PROFILE"

    # 2. Add alias to .bashrc_claude if not present
    ALIAS_NAME="${PROFILE}"
    if grep -qF "alias ${ALIAS_NAME}=" "$BASHRC_CLAUDE" 2>/dev/null; then
        echo -e "${YELLOW}[WARN]${NC} Alias $ALIAS_NAME already in .bashrc_claude"
    else
        # Insert before the end marker
        ALIAS_CMD=$(engine_launch_cmd "$PROFILE_CLI" "$PROFILES_DIR" "$PROFILE" "")
        ALIAS_LINE="alias ${ALIAS_NAME}='${ALIAS_CMD}'"
        TMPFILE=$(mktemp)
        awk -v line="$ALIAS_LINE" '/# === Fin Multi-Agent ===/ { print line }{ print }' "$BASHRC_CLAUDE" > "$TMPFILE" && mv "$TMPFILE" "$BASHRC_CLAUDE"
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
    PROFILE_CLI=$(engine_from_profile "$PROFILE")
    CONFIG_ENV=$(engine_config_env "$PROFILE_CLI")
    echo -e "${BLUE}[AUTH]${NC} Authenticating profile: $PROFILE ($PROFILE_CLI)"
    case "$PROFILE_CLI" in
        codex)
            # `codex login` : OAuth « Sign in with ChatGPT » — l'usage est
            # décompté sur l'abonnement, pas facturé au token.
            # [Documenté: developers.openai.com/codex/cli]
            echo -e "${BLUE}[AUTH]${NC} → choisir « Sign in with ChatGPT »"
            echo -e "${YELLOW}[WARN]${NC} PAS « Provide your own API key » :"
            echo -e "         facturation au token, hors forfait."
            echo ""
            env "$CONFIG_ENV=$PROFILES_DIR/$PROFILE" codex login </dev/tty >/dev/tty 2>&1

            # Vérifier ce qui a RÉELLEMENT été fait : un profil authentifié par
            # clé API facturerait au token sans jamais le signaler.
            if engine_codex_preflight "$PROFILES_DIR" "$PROFILE"; then
                echo -e "${GREEN}[OK]${NC}   Profil $PROFILE authentifié via ChatGPT (forfait)"
            else
                echo -e "${RED}[ERROR]${NC} Profil $PROFILE : authentification non conforme."
                echo -e "         Les agents refuseront de démarrer sur ce profil."
            fi
            ;;
        *)
            echo -e "${BLUE}[AUTH]${NC} Once authenticated, type /exit to continue"
            echo ""
            env "$CONFIG_ENV=$PROFILES_DIR/$PROFILE" claude </dev/tty >/dev/tty 2>&1
            ;;
    esac
    echo ""
    echo -e "${BLUE}[AUTH]${NC} Validating profile: $PROFILE (type /exit when done)"
    echo ""
    # E1 : relance en mode bypass avec le binaire ET la variable du bon moteur
    VALIDATE_CMD=$(engine_launch_cmd "$PROFILE_CLI" "$PROFILES_DIR" "$PROFILE" "")
    bash -c "$VALIDATE_CMD" </dev/tty >/dev/tty 2>&1
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
