#!/bin/bash
# upgrade.sh - Met à jour le framework depuis GitHub sans écraser les données projet
#
# Usage:
#   ./upgrade.sh              # Met à jour depuis main
#   ./upgrade.sh v2.1         # Met à jour vers un tag spécifique
#   ./upgrade.sh --dry-run    # Montre ce qui va changer sans appliquer

set -e

REPO_URL="https://github.com/OlesVanHermann/multi-agent.git"
DRY_RUN=false
BRANCH="main"

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *)         BRANCH="$arg" ;;
    esac
done

# Colors (compatible bash/zsh)
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

log_info() { printf "%s[INFO]%s %s\n" "$BLUE" "$NC" "$1"; }
log_ok()   { printf "%s[OK]%s %s\n" "$GREEN" "$NC" "$1"; }
log_warn() { printf "%s[WARN]%s %s\n" "$YELLOW" "$NC" "$1"; }
log_error(){ printf "%s[ERROR]%s %s\n" "$RED" "$NC" "$1"; }

# Détecter commandes
find_cmd() {
    local cmd_name="$1"; shift
    for cmd in "$@"; do
        local first_word="${cmd%% *}"
        if command -v "$first_word" &>/dev/null; then
            echo "$cmd"; return 0
        fi
    done
    log_error "Commande '$cmd_name' non trouvée."
    exit 1
}

GIT_CMD=$(find_cmd "git" git)
PIP_CMD=$(find_cmd "pip" pip3 pip "python3 -m pip")
RSYNC_CMD=$(find_cmd "rsync" rsync)

# ============================================================
# FRAMEWORK = mis à jour | PROJET = préservé
# ============================================================
FRAMEWORK_DIRS=(core scripts web docs upgrades tests infrastructure templates examples)
FRAMEWORK_FILES=(requirements.txt CLAUDE.md UPGRADE.md README.md LICENSE .gitignore)

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║       Multi-Agent Framework Upgrade        ║"
echo "╚════════════════════════════════════════════╝"
echo ""
log_info "Source: $REPO_URL ($BRANCH)"
[ "$DRY_RUN" = true ] && log_warn "Mode DRY-RUN — rien ne sera modifié"
echo ""

# ============================================================
# 1. Télécharger la nouvelle version
# ============================================================
TEMP_DIR=$(mktemp -d)
trap "rm -rf '$TEMP_DIR'" EXIT

log_info "Téléchargement..."
$GIT_CMD clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TEMP_DIR" 2>&1 | tail -1
log_ok "Téléchargé"
echo ""

# ============================================================
# 2. Afficher ce qui va changer
# ============================================================
echo "─── Répertoires framework ───"
echo ""
for dir in "${FRAMEWORK_DIRS[@]}"; do
    if [ -d "$TEMP_DIR/$dir" ]; then
        if [ -d "./$dir" ]; then
            # Compter les fichiers modifiés
            CHANGES=$($RSYNC_CMD -rn --delete --exclude='node_modules' --exclude='dist' "$TEMP_DIR/$dir/" "./$dir/" 2>/dev/null | grep -v "/$" | grep -v "^$" | grep -v "sending" | grep -v "total" | grep -v "sent " | wc -l | tr -d ' ')
            if [ "$CHANGES" -gt 0 ]; then
                printf "  ${YELLOW}↻${NC} %-20s %s fichiers modifiés\n" "$dir/" "$CHANGES"
            else
                printf "  ${GREEN}✓${NC} %-20s à jour\n" "$dir/"
            fi
        else
            printf "  ${YELLOW}+${NC} %-20s nouveau\n" "$dir/"
        fi
    fi
done

echo ""
echo "─── Fichiers framework ───"
echo ""
for file in "${FRAMEWORK_FILES[@]}"; do
    if [ -f "$TEMP_DIR/$file" ]; then
        if [ -f "./$file" ]; then
            if ! diff -q "$TEMP_DIR/$file" "./$file" &>/dev/null; then
                printf "  ${YELLOW}↻${NC} %s\n" "$file"
            else
                printf "  ${GREEN}✓${NC} %s (à jour)\n" "$file"
            fi
        else
            printf "  ${YELLOW}+${NC} %s (nouveau)\n" "$file"
        fi
    fi
done

echo ""
echo "─── Préservés (pas touchés) ───"
echo ""
for dir in prompts pool-requests project sessions logs; do
    [ -d "./$dir" ] && printf "  ✓ %s/\n" "$dir"
done
[ -f "./project-config.md" ] && printf "  ✓ project-config.md\n"
echo ""

# ============================================================
# Dry-run: on s'arrête là
# ============================================================
if [ "$DRY_RUN" = true ]; then
    log_warn "Dry-run terminé. Relancer sans --dry-run pour appliquer."
    echo ""
    exit 0
fi

# ============================================================
# 3. Appliquer la mise à jour
# ============================================================
log_info "Mise à jour..."

for dir in "${FRAMEWORK_DIRS[@]}"; do
    if [ -d "$TEMP_DIR/$dir" ]; then
        mkdir -p "./$dir"
        $RSYNC_CMD -a --delete --exclude='node_modules' --exclude='dist' "$TEMP_DIR/$dir/" "./$dir/"
        log_ok "$dir/"
    fi
done

for file in "${FRAMEWORK_FILES[@]}"; do
    if [ -f "$TEMP_DIR/$file" ]; then
        cp "$TEMP_DIR/$file" "./"
        log_ok "$file"
    fi
done

# ============================================================
# 4. Dépendances
# ============================================================
log_info "Installation des dépendances..."
$PIP_CMD install -q -r requirements.txt 2>/dev/null || \
$PIP_CMD install -q --break-system-packages -r requirements.txt 2>/dev/null || true
log_ok "Dépendances installées"

# ============================================================
# Résumé
# ============================================================
echo ""
echo "╔════════════════════════════════════════════╗"
echo "║            Mise à jour terminée            ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "  Lancer: ./scripts/agent.sh start all"
echo ""
