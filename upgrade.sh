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

# Colors (compatible bash/zsh)
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

log_info() { printf "%s[INFO]%s %s\n" "$BLUE" "$NC" "$1"; }
log_ok() { printf "%s[OK]%s %s\n" "$GREEN" "$NC" "$1"; }
log_warn() { printf "%s[WARN]%s %s\n" "$YELLOW" "$NC" "$1"; }
log_error() { printf "%s[ERROR]%s %s\n" "$RED" "$NC" "$1"; }

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
# ÉTAPE 1: Backup COMPLET du répertoire
# ============================================================
echo "─────────────────────────────────────────────"
log_info "Étape 1/5: Backup complet"
echo ""

CURRENT_DIR=$(basename "$(pwd)")
BACKUP_DIR="../${CURRENT_DIR}-backup-$(date +%Y%m%d-%H%M%S)"

if [ "$DRY_RUN" = false ]; then
    log_info "Création du backup complet..."

    # Backup complet (exclure les gros fichiers temporaires)
    mkdir -p "$BACKUP_DIR"
    rsync -a --exclude='.git' \
             --exclude='logs/*.log' \
             --exclude='sessions/*' \
             --exclude='__pycache__' \
             --exclude='*.pyc' \
             ./ "$BACKUP_DIR/"

    # Compter les fichiers
    FILE_COUNT=$(find "$BACKUP_DIR" -type f | wc -l | tr -d ' ')
    DIR_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

    echo ""
    log_ok "Backup complet créé:"
    echo "    📁 $BACKUP_DIR"
    echo "    📄 $FILE_COUNT fichiers"
    echo "    💾 $DIR_SIZE"
    echo ""
    echo "    Pour restaurer: rm -rf ./* && cp -r $BACKUP_DIR/* ./"
else
    log_warn "[DRY-RUN] Backup complet serait créé dans $BACKUP_DIR"
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
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TEMP_DIR"
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
    if command -v pip3 &>/dev/null; then
        pip3 install -q -r requirements.txt
    elif command -v pip &>/dev/null; then
        pip install -q -r requirements.txt
    else
        python3 -m pip install -q -r requirements.txt
    fi
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
    echo "Fichiers MIS À JOUR:"
    echo "  ↻ core/                 (framework)"
    echo "  ↻ scripts/              (framework)"
    echo "  ↻ docs/                 (framework)"
    echo "  ↻ requirements.txt      (dépendances)"
    echo ""
    echo "Fichiers PRÉSERVÉS:"
    echo "  ✓ prompts/              (vos prompts)"
    echo "  ✓ pool-requests/        (vos données)"
    echo "  ✓ project/              (votre code)"
    echo "  ✓ project-config.md     (votre config)"
    echo ""
    echo "Backup complet: $BACKUP_DIR"
    echo ""
    echo "⚠️  En cas de problème, restaurez avec:"
    echo "    rm -rf ./* && cp -r $BACKUP_DIR/* ./"
    echo ""
    echo "Prochaines étapes:"
    echo "  1. Lire upgrades/ pour les actions spécifiques"
    echo "  2. Lancer: ./scripts/bridge/start-bridge-agents.sh all"
else
    echo "[DRY-RUN] Aucune modification effectuée"
    echo "Relancez sans --dry-run pour appliquer"
fi
echo ""
