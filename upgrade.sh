#!/bin/bash
# upgrade.sh - Met à jour le framework depuis GitHub sans écraser les données locales
#
# Usage:
#   ./upgrade.sh              # Met à jour depuis main
#   ./upgrade.sh v2.1         # Met à jour vers un tag spécifique
#   ./upgrade.sh --dry-run    # Simule sans appliquer

set -e

REPO_URL="https://github.com/OlesVanHermann/multi-agent.git"
BRANCH="${1:-main}"
DRY_RUN=false

if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    BRANCH="${2:-main}"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║       Multi-Agent Framework Upgrade        ║"
echo "╚════════════════════════════════════════════╝"
echo ""
log_info "Source: $REPO_URL"
log_info "Branch/Tag: $BRANCH"
[ "$DRY_RUN" = true ] && log_warn "Mode DRY-RUN activé (simulation)"
echo ""

# ============================================================
# FICHIERS FRAMEWORK (seront mis à jour)
# ============================================================
FRAMEWORK_DIRS=(
    "core/"
    "scripts/"
    "docs/"
    "upgrades/"
)

FRAMEWORK_FILES=(
    "requirements.txt"
    "CLAUDE.md"
    "UPGRADE.md"
    "README.md"
    "LICENSE"
    ".gitignore"
)

# ============================================================
# FICHIERS PROJET (ne seront PAS touchés)
# ============================================================
# prompts/           - Vos prompts personnalisés
# pool-requests/     - Vos données (knowledge, pending, done...)
# project/           - Votre code source
# project-config.md  - Votre configuration
# logs/              - Vos logs
# sessions/          - Vos sessions

# ============================================================
# ÉTAPE 1: Backup des fichiers projet
# ============================================================
echo "─────────────────────────────────────────────"
log_info "Étape 1/5: Backup des fichiers projet"
echo ""

BACKUP_DIR="../multi-agent-backup-$(date +%Y%m%d-%H%M%S)"

if [ "$DRY_RUN" = false ]; then
    mkdir -p "$BACKUP_DIR"

    # Backup prompts (vos personnalisations)
    if [ -d "prompts/" ]; then
        cp -r prompts/ "$BACKUP_DIR/"
        log_ok "prompts/ → $BACKUP_DIR/prompts/"
    fi

    # Backup knowledge (vos inventaires)
    if [ -d "pool-requests/knowledge/" ]; then
        mkdir -p "$BACKUP_DIR/pool-requests/"
        cp -r pool-requests/knowledge/ "$BACKUP_DIR/pool-requests/"
        log_ok "pool-requests/knowledge/ → $BACKUP_DIR/"
    fi

    # Backup config
    if [ -f "project-config.md" ]; then
        cp project-config.md "$BACKUP_DIR/"
        log_ok "project-config.md → $BACKUP_DIR/"
    fi

    echo ""
    log_ok "Backup créé: $BACKUP_DIR"
else
    log_warn "[DRY-RUN] Backup serait créé dans $BACKUP_DIR"
fi

# ============================================================
# ÉTAPE 2: Arrêter les agents
# ============================================================
echo ""
echo "─────────────────────────────────────────────"
log_info "Étape 2/5: Arrêt des agents"
echo ""

if [ "$DRY_RUN" = false ]; then
    ./scripts/bridge/stop-bridge-agents.sh 2>/dev/null && log_ok "Agents bridge arrêtés" || true
    pkill -f "agent.py" 2>/dev/null && log_ok "Processus agent.py arrêtés" || true
else
    log_warn "[DRY-RUN] Les agents seraient arrêtés"
fi

# ============================================================
# ÉTAPE 3: Télécharger la nouvelle version
# ============================================================
echo ""
echo "─────────────────────────────────────────────"
log_info "Étape 3/5: Téléchargement de $BRANCH"
echo ""

TEMP_DIR=$(mktemp -d)
log_info "Téléchargement dans $TEMP_DIR..."

if [ "$DRY_RUN" = false ]; then
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TEMP_DIR" 2>&1 | grep -v "^Cloning"
    log_ok "Téléchargement terminé"
else
    log_warn "[DRY-RUN] git clone --depth 1 --branch $BRANCH $REPO_URL"
fi

# ============================================================
# ÉTAPE 4: Mise à jour des fichiers framework UNIQUEMENT
# ============================================================
echo ""
echo "─────────────────────────────────────────────"
log_info "Étape 4/5: Mise à jour des fichiers framework"
echo ""

log_info "Dossiers mis à jour:"
for dir in "${FRAMEWORK_DIRS[@]}"; do
    if [ -d "$TEMP_DIR/$dir" ]; then
        if [ "$DRY_RUN" = false ]; then
            rsync -av --delete "$TEMP_DIR/$dir" "./" | grep -v "/$" | head -5
            remaining=$(rsync -av --delete "$TEMP_DIR/$dir" "./" 2>/dev/null | grep -v "/$" | wc -l)
            [ "$remaining" -gt 5 ] && echo "  ... et $((remaining-5)) autres fichiers"
        fi
        log_ok "$dir"
    fi
done

echo ""
log_info "Fichiers mis à jour:"
for file in "${FRAMEWORK_FILES[@]}"; do
    if [ -f "$TEMP_DIR/$file" ]; then
        if [ "$DRY_RUN" = false ]; then
            cp "$TEMP_DIR/$file" "./"
        fi
        log_ok "$file"
    fi
done

# ============================================================
# ÉTAPE 5: Installation des dépendances
# ============================================================
echo ""
echo "─────────────────────────────────────────────"
log_info "Étape 5/5: Installation des dépendances"
echo ""

if [ "$DRY_RUN" = false ]; then
    pip install -q -r requirements.txt
    log_ok "Dépendances installées"
else
    log_warn "[DRY-RUN] pip install -r requirements.txt"
fi

# ============================================================
# NETTOYAGE
# ============================================================
if [ "$DRY_RUN" = false ]; then
    rm -rf "$TEMP_DIR"
fi

# ============================================================
# RÉSUMÉ
# ============================================================
echo ""
echo "╔════════════════════════════════════════════╗"
echo "║            Mise à jour terminée            ║"
echo "╚════════════════════════════════════════════╝"
echo ""

if [ "$DRY_RUN" = false ]; then
    echo "Fichiers PRÉSERVÉS (non modifiés):"
    echo "  ✓ prompts/              (vos prompts)"
    echo "  ✓ pool-requests/        (vos données)"
    echo "  ✓ project/              (votre code)"
    echo "  ✓ project-config.md     (votre config)"
    echo ""
    echo "Backup: $BACKUP_DIR"
    echo ""
    echo "Prochaines étapes:"
    echo "  1. Lire upgrades/ pour les actions spécifiques"
    echo "  2. Lancer: ./scripts/bridge/start-bridge-agents.sh all"
else
    echo "[DRY-RUN] Aucune modification effectuée"
    echo "Relancez sans --dry-run pour appliquer"
fi
echo ""
