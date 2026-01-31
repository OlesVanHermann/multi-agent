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

# ============================================================
# Détection automatique des commandes
# ============================================================
find_cmd() {
    local cmd_name="$1"
    shift
    for cmd in "$@"; do
        # Gérer les commandes multi-mots comme "python3 -m pip"
        local first_word="${cmd%% *}"
        if command -v "$first_word" &>/dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    log_error "Commande '$cmd_name' non trouvée. Essayé: $*"
    exit 1
}

# Détecter les commandes disponibles
GIT_CMD=$(find_cmd "git" git)
PIP_CMD=$(find_cmd "pip" pip3 pip "python3 -m pip" "python -m pip")
PYTHON_CMD=$(find_cmd "python" python3 python)
RSYNC_CMD=$(find_cmd "rsync" rsync)
FIND_CMD=$(find_cmd "find" gfind find)
DU_CMD=$(find_cmd "du" gdu du)

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
    $RSYNC_CMD -a --exclude='.git' \
             --exclude='logs/*.log' \
             --exclude='sessions/*' \
             --exclude='__pycache__' \
             --exclude='*.pyc' \
             ./ "$BACKUP_DIR/"

    # Compter les fichiers
    FILE_COUNT=$($FIND_CMD "$BACKUP_DIR" -type f | wc -l | tr -d ' ')
    DIR_SIZE=$($DU_CMD -sh "$BACKUP_DIR" | cut -f1)

    echo ""
    log_ok "Backup complet créé:"
    echo "    📁 $BACKUP_DIR"
    echo "    📄 $FILE_COUNT fichiers"
    echo "    💾 $DIR_SIZE"
    echo ""
    echo "    Pour restaurer: mv ./* ./removed/ && cp -r $BACKUP_DIR/* ./"
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
    $GIT_CMD clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TEMP_DIR"
    log_ok "Téléchargement terminé"
else
    log_warn "[DRY-RUN] $GIT_CMD clone --depth 1 --branch $BRANCH $REPO_URL"
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
    # Enlever le / final pour avoir le nom du dossier
    dir_name="${dir%/}"
    if [ -d "$TEMP_DIR/$dir_name" ]; then
        if [ "$DRY_RUN" = false ]; then
            # Créer le dossier destination s'il n'existe pas
            mkdir -p "./$dir_name"
            # Sync DANS le dossier (avec trailing slash) pour ne supprimer que le contenu du dossier
            $RSYNC_CMD -av --delete "$TEMP_DIR/$dir_name/" "./$dir_name/" 2>&1 | grep -v "/$" | head -5 || true
        fi
        log_ok "$dir_name/"
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
    $PIP_CMD install -q -r requirements.txt
    log_ok "Dépendances installées"
else
    log_warn "[DRY-RUN] $PIP_CMD install -r requirements.txt"
fi

# ============================================================
# NETTOYAGE
# ============================================================
if [ "$DRY_RUN" = false ]; then
    mkdir -p ./removed
    mv "$TEMP_DIR" "./removed/temp-upgrade-$(date +%s)" 2>/dev/null || true
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
    echo "    mv ./* ./removed/ && cp -r $BACKUP_DIR/* ./"
    echo ""
    echo "Prochaines étapes:"
    echo "  1. Lire upgrades/ pour les actions spécifiques"
    echo "  2. Lancer: ./scripts/bridge/start-bridge-agents.sh all"
else
    echo "[DRY-RUN] Aucune modification effectuée"
    echo "Relancez sans --dry-run pour appliquer"
fi
echo ""
