#!/bin/bash
# install_bashrc_claude.sh — Crée ~/.bashrc_claude avec les alias multi-profils Claude Code
#                            et ajoute la ligne source dans ~/.bashrc
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

# ── Colors ──────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# ── Vérifications ────────────────────────────────────────────────────────────

if [ ! -d "$MA_DIR/login" ]; then
    warn "Répertoire $MA_DIR/login absent — les alias seront créés mais les profils devront"
    warn "être initialisés ensuite avec : cd $MA_DIR && source setup/create_login.sh claude1a claude1b ..."
fi

# ── Générer ~/.bashrc_claude ─────────────────────────────────────────────────

info "Création de $BASHRC_CLAUDE ..."

cat > "$BASHRC_CLAUDE" << EOF
# === Claude Code Multi-Profils ===
# Source this file from .bashrc: [ -f ~/.bashrc_claude ] && source ~/.bashrc_claude

export CLAUDE_PROFILES_DIR="$MA_DIR/login"

alias claude='claude --dangerously-skip-permissions'

alias claude1a='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude1a claude --dangerously-skip-permissions'
alias claude1b='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude1b claude --dangerously-skip-permissions'
alias claude2a='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude2a claude --dangerously-skip-permissions'
alias claude2b='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude2b claude --dangerously-skip-permissions'
alias claude3a='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude3a claude --dangerously-skip-permissions'
alias claude3b='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude3b claude --dangerously-skip-permissions'
alias claude4a='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude4a claude --dangerously-skip-permissions'
alias claude4b='CLAUDE_CONFIG_DIR=$MA_DIR/login/claude4b claude --dangerously-skip-permissions'
# === Fin Claude Code ===
EOF

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
echo "  Alias disponibles : claude1a claude1b claude2a claude2b"
echo "                      claude3a claude3b claude4a claude4b"
echo ""
echo "  Pour activer immédiatement (sans relancer le shell) :"
echo -e "  ${CYAN}source ~/.bashrc_claude${NC}"
echo ""
echo "  Pour créer les profils (authentification interactive) :"
echo -e "  ${CYAN}cd $MA_DIR && source setup/create_login.sh claude1a claude1b claude2a claude2b${NC}"
