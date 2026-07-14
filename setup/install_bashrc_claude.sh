#!/bin/bash
# install_bashrc_claude.sh — Crée ~/.bashrc_claude avec les alias multi-profils
#                            et ajoute la ligne source dans ~/.bashrc
#
# E1 : les alias sont GÉNÉRÉS depuis engines.sh, pas écrits en dur. Le moteur de
#      chaque profil vient du préfixe de son nom (claude1a → claude, codex1a →
#      codex), donc la bonne variable d'auth (CLAUDE_CONFIG_DIR / CODEX_HOME) et
#      le bon binaire. Une liste figée d'alias `claude*` produisait des alias
#      cassés dès qu'un profil codex existait.
#
# Usage: ./setup/install_bashrc_claude.sh [chemin_multi_agent]
#
# Exemple:
#   ./setup/install_bashrc_claude.sh                     # auto-détecte ~/multi-agent
#   ./setup/install_bashrc_claude.sh /home/ubuntu/multi-agent

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────

MA_DIR="${1:-$HOME/multi-agent}"
BASHRC_CLAUDE="$HOME/.bashrc_claude"
BASHRC="$HOME/.bashrc"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/engines.sh"

# Profils par défaut si login/ est vide (bootstrap d'une install neuve)
DEFAULT_PROFILES=(claude1a claude1b claude2a claude2b claude3a claude3b claude4a claude4b)

# ── Colors ──────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# ── Vérifications ────────────────────────────────────────────────────────────

if [ ! -d "$MA_DIR/login" ]; then
    warn "Répertoire $MA_DIR/login absent — les alias seront créés mais les profils devront"
    warn "être initialisés ensuite avec : cd $MA_DIR && source setup/login_create.sh claude1a codex1a ..."
fi

# ── Profils à aliaser : ceux réellement présents dans login/, sinon les défauts ──

PROFILES=()
if [ -d "$MA_DIR/login" ]; then
    for d in "$MA_DIR"/login/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        engine_profile_is_valid "$name" || continue
        PROFILES+=("$name")
    done
fi
if [ ${#PROFILES[@]} -eq 0 ]; then
    PROFILES=("${DEFAULT_PROFILES[@]}")
    info "Aucun profil dans login/ — génération des alias par défaut"
fi

# ── Générer ~/.bashrc_claude ─────────────────────────────────────────────────

info "Création de $BASHRC_CLAUDE ..."

{
    echo "# === Multi-Agent : profils CLI (${ENGINES[*]}) ==="
    echo "# Source this file from .bashrc: [ -f ~/.bashrc_claude ] && source ~/.bashrc_claude"
    echo ""
    echo "export CLAUDE_PROFILES_DIR=\"$MA_DIR/login\""
    echo ""
    # Alias « nu » par moteur : `claude`, `codex`… en mode bypass
    for cli in "${ENGINES[@]}"; do
        echo "alias ${cli}='$(engine_launch_cmd "$cli" "$MA_DIR/login" "" "")'"
    done
    echo ""
    # Un alias par profil, avec la variable d'auth de SON moteur
    for profile in "${PROFILES[@]}"; do
        cli=$(engine_from_profile "$profile") || continue
        echo "alias ${profile}='$(engine_launch_cmd "$cli" "$MA_DIR/login" "$profile" "")'"
    done
    echo "# === Fin Multi-Agent ==="
} > "$BASHRC_CLAUDE"

ok "Créé : $BASHRC_CLAUDE"

# ── Ajouter source dans ~/.bashrc si absent ───────────────────────────────────

SOURCE_LINE='[ -f ~/.bashrc_claude ] && source ~/.bashrc_claude'

if grep -qF 'bashrc_claude' "$BASHRC" 2>/dev/null; then
    info "~/.bashrc contient déjà la ligne source — rien à faire"
else
    echo "" >> "$BASHRC"
    echo "# Claude Code profiles" >> "$BASHRC"
    echo "$SOURCE_LINE" >> "$BASHRC"
    ok "Ajouté dans ~/.bashrc : $SOURCE_LINE"
fi

# ── Résumé ───────────────────────────────────────────────────────────────────

echo ""
ok "Installation terminée."
echo ""
echo "  Profils configurés pour : $MA_DIR/login/"
echo "  Alias disponibles : ${PROFILES[*]}"
echo ""
echo "  Pour activer immédiatement (sans relancer le shell) :"
echo -e "  ${CYAN}source ~/.bashrc_claude${NC}"
echo ""
echo "  Pour créer les profils (authentification interactive) :"
echo -e "  ${CYAN}cd $MA_DIR && source setup/login_create.sh claude1a claude1b codex1a${NC}"
