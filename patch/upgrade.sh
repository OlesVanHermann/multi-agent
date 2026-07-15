#!/bin/bash
# Actions manuelles (systemd, overrides projet) : patch/HOW_TO_UPGRADE.md
# upgrade.sh - Met à jour le framework depuis GitHub sans écraser les données projet
#
# Usage:
#   ./upgrade.sh              # Met à jour depuis main
#   ./upgrade.sh v2.1         # Met à jour vers un tag spécifique
#   ./upgrade.sh --dry-run    # Montre ce qui va changer sans appliquer

set -e

# Surchargeable pour un miroir local/air-gapped : MA_UPGRADE_REPO_URL=file:///chemin
REPO_URL="${MA_UPGRADE_REPO_URL:-https://github.com/OlesVanHermann/multi-agent.git}"
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
PYTHON_CMD=$(find_cmd "python3" python3 python)

# Version affichée dans CLAUDE.md ("Multi-Agent System vX.Y.Z")
version_of() {
    grep -m1 -oE 'Multi-Agent System v[0-9][0-9.]*' "$1" 2>/dev/null \
        | grep -oE 'v[0-9][0-9.]*' || echo "?"
}

# ============================================================
# FRAMEWORK = mis à jour | PROJET = préservé
# ============================================================
FRAMEWORK_DIRS=(scripts web docs patch setup tests templates examples framework .github)
FRAMEWORK_FILES=(requirements.txt CLAUDE.md README.md LICENSE .gitignore)

# Fichiers canoniques de prompts/ (contrat framework — RULES.md §10 verify…).
# Tout le reste de prompts/ (répertoires d'agents, *.model, *.login) est projet.
# Voir patch/HOW_TO_UPGRADE.md, section « Migration v3.0.x → v3.1.x », pour
# les opérations manuelles (AGENTS.md, modèles GPT, slots et liens .login).
PROMPTS_CANONICAL=(RULES.md CONVENTIONS.md PATHS.md AGENT.md CHROME.md)

# Miroir exact de FRAMEWORK_PATHS dans hub-release.sh (manifest de checksums).
# Verrouillé par tests/test_upgrade_manifest_sync.py — modifier les deux ensemble.
MANIFEST_PATHS=(scripts web docs patch setup tests templates examples framework .github bench
                'login/*/settings.json'
                prompts/RULES.md prompts/CONVENTIONS.md prompts/PATHS.md
                prompts/AGENT.md prompts/CHROME.md
                requirements.txt CLAUDE.md README.md LICENSE .gitignore)

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

LOCAL_VERSION=$(version_of ./CLAUDE.md)
NEW_VERSION=$(version_of "$TEMP_DIR/CLAUDE.md")
log_info "Version locale : $LOCAL_VERSION → cible : $NEW_VERSION"
echo ""

# ============================================================
# 1b. Vérifier l'intégrité du framework téléchargé (C3)
#     Les agents tournent en bypass-permissions : ne jamais appliquer
#     une mise à jour altérée. MA_UPGRADE_STRICT=1 rend manifest ET
#     signature de tag obligatoires.
# ============================================================
STRICT="${MA_UPGRADE_STRICT:-0}"

# Signature GPG du tag (si BRANCH est un tag)
if $GIT_CMD -C "$TEMP_DIR" rev-parse -q --verify "refs/tags/$BRANCH" >/dev/null 2>&1; then
    if $GIT_CMD -C "$TEMP_DIR" verify-tag "$BRANCH" >/dev/null 2>&1; then
        log_ok "Signature GPG du tag $BRANCH vérifiée"
    elif [ "$STRICT" = "1" ]; then
        log_error "Tag $BRANCH non signé ou signature invérifiable (MA_UPGRADE_STRICT=1)."
        log_error "Importer la clé publique de release puis réessayer."
        exit 1
    else
        log_warn "Tag $BRANCH : signature absente ou invérifiable (clé publique non importée ?)"
    fi
fi

# Manifest de checksums des fichiers framework
MANIFEST="$TEMP_DIR/patch/checksums.sha256"
if [ -f "$MANIFEST" ]; then
    log_info "Vérification des checksums framework..."
    if ! (cd "$TEMP_DIR" && LC_ALL=C sha256sum --quiet -c patch/checksums.sha256); then
        log_error "ÉCART DE CHECKSUM : le framework téléchargé ne correspond pas au manifest."
        log_error "Mise à jour ABANDONNÉE — rien n'a été modifié."
        exit 1
    fi
    # Détecter des fichiers framework présents mais absents du manifest
    EXTRA_FILES=$(comm -23 \
        <($GIT_CMD -C "$TEMP_DIR" ls-files -- "${MANIFEST_PATHS[@]}" ':!patch/checksums.sha256' | LC_ALL=C sort) \
        <(sed 's/^[0-9a-f]\{64\}[ *]\{2\}//' "$MANIFEST" | LC_ALL=C sort))
    if [ -n "$EXTRA_FILES" ]; then
        log_error "Fichiers framework hors manifest (ajout non attendu) :"
        echo "$EXTRA_FILES" | sed 's/^/    /'
        log_warn "NB : cibler une release plus ancienne que cet upgrade.sh (manifest"
        log_warn "généré avec une liste plus courte) produit aussi cet écart."
        log_error "Mise à jour ABANDONNÉE — rien n'a été modifié."
        exit 1
    fi
    log_ok "Intégrité vérifiée ($(grep -c . "$MANIFEST") fichiers)"
elif [ "$STRICT" = "1" ]; then
    log_error "patch/checksums.sha256 absent de la release (MA_UPGRADE_STRICT=1)."
    exit 1
else
    log_warn "patch/checksums.sha256 absent (release antérieure à C3) — intégrité non vérifiée"
fi
echo ""

# ============================================================
# 2. Afficher ce qui va changer
# ============================================================
echo "─── Répertoires framework ───"
echo ""
for dir in "${FRAMEWORK_DIRS[@]}"; do
    if [ -d "$TEMP_DIR/$dir" ]; then
        if [ -d "./$dir" ]; then
            # Compter les fichiers modifiés (-i : sans itemize, rsync -n est muet ;
            # --checksum : le clone est frais, les mtimes seuls diffèrent toujours ;
            # -l : sans lui, les symlinks produisent un « skipping » compté à tort)
            CHANGES=$($RSYNC_CMD -rlni --checksum --delete --exclude='node_modules' --exclude='dist' --exclude='secrets.cfg' "$TEMP_DIR/$dir/" "./$dir/" 2>/dev/null | grep -v "/$" | grep -v "^$" | wc -l | tr -d ' ')
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
echo "─── Migrations (idempotentes — v2→v3 comme v3.X→v3.X+1) ───"
echo ""

# bench/ : fusion, jamais de suppression (tâches importées sur site préservées)
if [ -d "$TEMP_DIR/bench" ]; then
    BENCH_OPTS=(--exclude=results)
    [ -f "./bench/heldout.txt" ] && BENCH_OPTS+=(--exclude=heldout.txt)
    if [ -d "./bench" ]; then
        BENCH_CHANGES=$($RSYNC_CMD -rlni --checksum "${BENCH_OPTS[@]}" "$TEMP_DIR/bench/" "./bench/" 2>/dev/null | grep -v "/$" | grep -v "^$" | wc -l | tr -d ' ')
        if [ "$BENCH_CHANGES" -gt 0 ]; then
            printf "  ${YELLOW}⇄${NC} %-20s fusion : %s fichiers framework à mettre à jour (results/ et heldout.txt locaux préservés)\n" "bench/" "$BENCH_CHANGES"
        else
            printf "  ${GREEN}✓${NC} %-20s à jour (fusion)\n" "bench/"
        fi
    else
        printf "  ${YELLOW}+${NC} %-20s nouveau (banc V3)\n" "bench/"
    fi
fi

# prompts/ canoniques : contrat framework
for f in "${PROMPTS_CANONICAL[@]}"; do
    [ -f "$TEMP_DIR/prompts/$f" ] || continue
    if [ -L "./prompts/$f" ]; then
        printf "  ${YELLOW}!${NC} prompts/%s : lien symbolique local — ne sera pas touché\n" "$f"
    elif [ ! -f "./prompts/$f" ]; then
        printf "  ${YELLOW}+${NC} prompts/%s (nouveau)\n" "$f"
    elif ! diff -q "$TEMP_DIR/prompts/$f" "./prompts/$f" &>/dev/null; then
        printf "  ${YELLOW}↻${NC} prompts/%s (backup dans removed/ avant remplacement)\n" "$f"
    else
        printf "  ${GREEN}✓${NC} prompts/%s (à jour)\n" "$f"
    fi
done

# Règles deny (protection oracle V3) dans les profils login existants
DENY_REF="$TEMP_DIR/login/claude1a/settings.json"
DENY_MERGE="$TEMP_DIR/patch/merge-deny-rules.py"
if [ -f "$DENY_REF" ] && [ -f "$DENY_MERGE" ] && compgen -G "./login/claude*/settings.json" > /dev/null; then
    $PYTHON_CMD "$DENY_MERGE" --check "$DENY_REF" ./login/claude*/settings.json | sed 's/^/  /'
fi

echo ""
echo "─── Préservés (pas touchés) ───"
echo ""
for dir in pool-requests project sessions logs; do
    [ -d "./$dir" ] && printf "  ✓ %s/\n" "$dir"
done
[ -d "./prompts" ] && printf "  ✓ prompts/ (répertoires d'agents, *.model, *.login — seuls les %s .md canoniques sont synchronisés)\n" "${#PROMPTS_CANONICAL[@]}"
[ -d "./login" ] && printf "  ✓ login/ (credentials — seules les règles deny sont fusionnées)\n"
[ -d "./bench/results" ] && printf "  ✓ bench/results/ + bench/heldout.txt (données de site)\n"
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
# 3. Sauvegarder les secrets avant mise à jour
# ============================================================
SECRETS_BACKUP=""
if [ -f "./setup/secrets.cfg" ]; then
    SECRETS_BACKUP=$(mktemp)
    cp "./setup/secrets.cfg" "$SECRETS_BACKUP"
    log_info "secrets.cfg sauvegardé"
fi

# ============================================================
# 4. Appliquer la mise à jour
#    Safe-delete (C3) : l'état actuel est archivé dans removed/
#    avant le rsync --delete — aucune suppression définitive.
# ============================================================
log_info "Mise à jour..."

BACKUP_DIR="./removed/$(date +%Y%m%d_%H%M%S)_upgrade_backup"
mkdir -p "$BACKUP_DIR"
log_info "Sauvegarde de l'état actuel dans $BACKUP_DIR"

for dir in "${FRAMEWORK_DIRS[@]}"; do
    if [ -d "$TEMP_DIR/$dir" ]; then
        if [ -d "./$dir" ]; then
            $RSYNC_CMD -a --exclude='node_modules' --exclude='dist' --exclude='secrets.cfg' "./$dir/" "$BACKUP_DIR/$dir/"
        fi
        mkdir -p "./$dir"
        $RSYNC_CMD -a --delete --exclude='node_modules' --exclude='dist' --exclude='secrets.cfg' "$TEMP_DIR/$dir/" "./$dir/"
        log_ok "$dir/"
    fi
done

# ============================================================
# 5. Restaurer les secrets
# ============================================================
if [ -n "$SECRETS_BACKUP" ]; then
    cp "$SECRETS_BACKUP" "./setup/secrets.cfg"
    rm -f "$SECRETS_BACKUP"
    log_ok "secrets.cfg restauré"
elif [ ! -f "./setup/secrets.cfg" ] && [ -f "./setup/secrets.cfg.example" ]; then
    cp "./setup/secrets.cfg.example" "./setup/secrets.cfg"
    log_warn "secrets.cfg créé depuis template — PENSEZ À LE CONFIGURER"
fi

for file in "${FRAMEWORK_FILES[@]}"; do
    if [ -f "$TEMP_DIR/$file" ] || [ -L "$TEMP_DIR/$file" ]; then
        cp -a --remove-destination "$TEMP_DIR/$file" "./$file"
        log_ok "$file"
    fi
done

# ============================================================
# 6. Migrations (idempotentes — v2→v3 comme v3.X→v3.X+1)
# ============================================================

# 6a. bench/ : fusion SANS --delete — les tâches importées sur site et les
#     résultats locaux survivent ; le heldout.txt local (split du site) fait foi.
if [ -d "$TEMP_DIR/bench" ]; then
    BENCH_OPTS=(--exclude=results)
    [ -f "./bench/heldout.txt" ] && BENCH_OPTS+=(--exclude=heldout.txt)
    if [ -d "./bench" ]; then
        $RSYNC_CMD -a --exclude=results "./bench/" "$BACKUP_DIR/bench/"
    fi
    mkdir -p ./bench
    $RSYNC_CMD -a "${BENCH_OPTS[@]}" "$TEMP_DIR/bench/" "./bench/"
    mkdir -p ./bench/results
    log_ok "bench/ (fusion — results/ et heldout.txt locaux préservés)"
fi

# 6b. prompts/ canoniques : contrat framework (RULES.md §10 verify…).
#     Les répertoires d'agents XXX-*/ et les *.model/*.login ne sont pas touchés.
for f in "${PROMPTS_CANONICAL[@]}"; do
    [ -f "$TEMP_DIR/prompts/$f" ] || continue
    if [ -L "./prompts/$f" ]; then
        log_warn "prompts/$f : lien symbolique local — non touché"
        continue
    fi
    if [ -f "./prompts/$f" ] && diff -q "$TEMP_DIR/prompts/$f" "./prompts/$f" &>/dev/null; then
        continue
    fi
    mkdir -p ./prompts "$BACKUP_DIR/prompts"
    [ -f "./prompts/$f" ] && cp "./prompts/$f" "$BACKUP_DIR/prompts/$f"
    cp "$TEMP_DIR/prompts/$f" "./prompts/$f"
    log_ok "prompts/$f"
done

# 6c. Règles deny (protection oracle V3) : fusion dans les profils login
#     existants. Référence = release téléchargée (couverte par le manifest) ;
#     union des règles uniquement, le reste du settings.json ne bouge pas.
DENY_REF="$TEMP_DIR/login/claude1a/settings.json"
DENY_MERGE="$TEMP_DIR/patch/merge-deny-rules.py"
if [ -f "$DENY_REF" ] && [ -f "$DENY_MERGE" ] && compgen -G "./login/claude*/settings.json" > /dev/null; then
    mkdir -p "$BACKUP_DIR/login"
    for s in ./login/claude*/settings.json; do
        d="$BACKUP_DIR/login/$(basename "$(dirname "$s")")"
        mkdir -p "$d"
        cp "$s" "$d/"
    done
    $PYTHON_CMD "$DENY_MERGE" "$DENY_REF" ./login/claude*/settings.json
fi

# ============================================================
# 7. Dépendances
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
echo "  Version : $LOCAL_VERSION → $NEW_VERSION"
echo "  Redémarrer les agents (nouveau bridge) :"
echo "    ./scripts/agent.sh stop all && ./scripts/agent.sh start all"
echo ""
