#!/bin/bash
# Bootstrap du système multi-agent x45
# Usage: ./scripts/x45-bootstrap.sh [project_dir]
#
# Copie les templates x45 dans prompts/, crée l'arborescence projet,
# et vérifie que tout est prêt.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
TEMPLATES_DIR="$ROOT/templates/x45"
PROJECT_DIR="${1:-$ROOT/project}"

echo "=== Bootstrap x45 ==="
echo "Root: $ROOT"
echo "Templates: $TEMPLATES_DIR"
echo "Project: $PROJECT_DIR"

# Verify templates exist
if [ ! -d "$TEMPLATES_DIR/prompts" ]; then
    echo "ERROR: templates/x45/prompts/ not found!"
    echo "Make sure you're running from the multi-agent root directory."
    exit 1
fi

# 1. Copy prompts templates
echo ""
echo "--- Copie des prompts x45 ---"
if [ -f "$ROOT/prompts/AGENT.md" ]; then
    echo "  AGENT.md already exists, skipping"
else
    cp "$TEMPLATES_DIR/prompts/AGENT.md" "$ROOT/prompts/AGENT.md"
    echo "  AGENT.md copié"
fi

for agent_dir in "$TEMPLATES_DIR/prompts"/[0-9]*/; do
    [ -d "$agent_dir" ] || continue
    agent_id=$(basename "$agent_dir")
    target="$ROOT/prompts/$agent_id"

    if [ -d "$target" ]; then
        echo "  $agent_id/ already exists, skipping"
        continue
    fi

    mkdir -p "$target"
    cp "$agent_dir"/*.md "$target/"
    echo "  $agent_id/ copié ($(ls "$target"/*.md 2>/dev/null | wc -l) fichiers)"
done

# 2. Create AGENT.md symlinks
echo ""
echo "--- Symlinks AGENT.md ---"
for dir in "$ROOT"/prompts/*/; do
    agent_id=$(basename "$dir")
    [ -f "$dir/system.md" ] || continue
    if [ ! -L "$dir/agent.md" ]; then
        ln -sf ../AGENT.md "$dir/agent.md"
        echo "  $agent_id/agent.md → ../AGENT.md"
    fi
done

# 3. Create project directory structure
echo ""
echo "--- Arborescence projet ---"
mkdir -p "$PROJECT_DIR"/{raw,clean,index,pipeline,bilans,logs}
echo "  $PROJECT_DIR/raw/          ← données brutes"
echo "  $PROJECT_DIR/clean/        ← markdown nettoyé (200)"
echo "  $PROJECT_DIR/index/        ← vecteurs cherchables (600)"
echo "  $PROJECT_DIR/pipeline/     ← outputs des 3XX"
echo "  $PROJECT_DIR/bilans/       ← bilans (500)"
echo "  $PROJECT_DIR/logs/         ← logs agents"

# 4. Check Redis
echo ""
echo "--- Redis ---"
if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null 2>&1; then
    echo "  Redis OK"
else
    echo "  ⚠ Redis non disponible. Lancer: ./scripts/infra.sh start"
fi

# 5. Verify files
echo ""
echo "--- Vérification ---"
TOTAL=0
OK=0
MISSING=""
for dir in "$ROOT"/prompts/*/; do
    agent_id=$(basename "$dir")
    [ -f "$dir/system.md" ] || continue
    for f in system.md memory.md methodology.md; do
        TOTAL=$((TOTAL + 1))
        if [ -f "$dir/$f" ]; then
            OK=$((OK + 1))
        else
            MISSING="$MISSING  $agent_id/$f\n"
        fi
    done
done

echo "  $OK/$TOTAL fichiers OK"
if [ -n "$MISSING" ]; then
    echo "  Manquants:"
    echo -e "$MISSING"
fi

# 6. Summary
echo ""
echo "--- Chaîne de traitement ---"
echo ""
echo "  BOOTSTRAP: human → 900 → 945 → tous les system.md"
echo ""
echo "  DATA:      raw/ → 200 → clean/ → 600 → index/"
echo ""
echo "  PIPELINE:  3XX chaîne → output-final/"
echo ""
echo "  FEEDBACK:"
echo "    court:   500 → 8XX → methodology.md → 3XX"
echo "    long:    500 → 945 → system.md → tous"
echo ""
echo "--- Prochaines étapes ---"
echo ""
echo "  1. Mettre les données brutes dans project/raw/"
echo "  2. Éditer prompts/900/memory.md (orientation du projet)"
echo "  3. ./scripts/infra.sh start"
echo "  4. ./scripts/send.sh 900 \"go\""
echo "  5. ./scripts/agent.sh start 945"
echo "  6. ./scripts/send.sh 945 \"go\""
echo "  7. ./scripts/agent.sh start all"
echo "  8. ./scripts/send.sh 200 \"go\""
echo ""
echo "  Voir: docs/X45-METHODOLOGY.md pour la doc complète"
echo ""
echo "=== Prêt ==="
