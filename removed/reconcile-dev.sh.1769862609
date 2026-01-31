#!/bin/bash
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Réconciliation: Créer les PR-DEV manquants pour les fonctions ❌ dans INVENTORY
#

PR_DIR="$BASE_DIR/pool-requests"
INVENTORY_DIR="$PR_DIR/knowledge"
NEXT_ID_FILE="$PR_DIR/NEXT_ID"

echo "=== Réconciliation INVENTORY → PR-DEV ==="
echo ""

# Lire le prochain ID
NEXT_ID=$(cat "$NEXT_ID_FILE" 2>/dev/null || echo 2000)
INITIAL_ID=$NEXT_ID

# Compteurs
created=0
skipped=0

# Agent mapping
get_agent() {
    case "$1" in
        EXCEL) echo "300" ;;
        WORD)  echo "301" ;;
        PPTX)  echo "302" ;;
        PDF)   echo "303" ;;
    esac
}

# Pour chaque format
for FORMAT in EXCEL WORD PPTX PDF; do
    INVENTORY_FILE="$INVENTORY_DIR/INVENTORY-${FORMAT}.md"
    [ -f "$INVENTORY_FILE" ] || continue

    AGENT=$(get_agent "$FORMAT")
    FORMAT_LOWER=$(echo "$FORMAT" | tr '[:upper:]' '[:lower:]')

    echo "Traitement $FORMAT (Agent $AGENT)..."

    # Extraire les lignes avec ❌
    # Format: | excel_get_all_comments | ❌ | ApiWorksheet.GetAllComments |
    grep "❌" "$INVENTORY_FILE" | while read -r line; do
        # Extraire le nom de la fonction MCP (première colonne)
        mcp_func=$(echo "$line" | awk -F'|' '{print $2}' | tr -d ' ')

        # Extraire l'API (troisième colonne)
        api_func=$(echo "$line" | awk -F'|' '{print $4}' | tr -d ' ')

        if [ -z "$mcp_func" ]; then
            continue
        fi

        # Vérifier si un PR-SPEC existe déjà pour cette fonction
        existing_spec=$(grep -l "## Fonction" "$PR_DIR"/pending/PR-SPEC-${AGENT}-*.md "$PR_DIR"/done/PR-SPEC-${AGENT}-*.md 2>/dev/null | xargs grep -l "$mcp_func" 2>/dev/null | head -1)
        if [ -n "$existing_spec" ]; then
            skipped=$((skipped + 1))
            continue
        fi

        # Vérifier si un PR-DEV existe déjà
        existing_dev=$(grep -l "$mcp_func" "$PR_DIR"/pending/PR-DEV-${AGENT}-*.md 2>/dev/null | head -1)
        if [ -n "$existing_dev" ]; then
            skipped=$((skipped + 1))
            continue
        fi

        # Créer le PR-DEV
        cat > "$PR_DIR/pending/PR-DEV-${AGENT}-${NEXT_ID}.md" << EOF
# PR-DEV-${AGENT}-${NEXT_ID}

## Feature
${mcp_func}

## Agent cible
${AGENT} (${FORMAT})

## Source API
${api_func}

## Description
Implémenter la fonction ${mcp_func} basée sur ${api_func} de l'API OnlyOffice.

## Priorité
normale

## Créé par
reconcile-dev.sh

## Date
$(date +%Y-%m-%d)

## Note
Créé par réconciliation (fonction ❌ dans INVENTORY sans PR-SPEC)
EOF

        NEXT_ID=$((NEXT_ID + 1))
        created=$((created + 1))
    done
done

# Mettre à jour NEXT_ID
echo "$NEXT_ID" > "$NEXT_ID_FILE"

echo ""
echo "Résultat:"
echo "  Créés:  $created"
echo "  Skippés: $skipped"
echo ""

if [ "$created" -gt 0 ]; then
    echo "Commit des nouveaux PR-DEV..."
    cd "$PR_DIR"
    git add pending/PR-DEV-*.md NEXT_ID
    git commit -m "reconcile: created $created missing PR-DEV from INVENTORY"

    echo ""
    echo "Injection dans la queue 200..."
    count=0
    for f in "$PR_DIR"/pending/PR-DEV-*.md; do
        [ -f "$f" ] || continue
        pr=$(basename "$f" .md)
        redis-cli RPUSH "ma:inject:200" "$pr" > /dev/null
        count=$((count + 1))
    done
    echo "Injecté $count PR-DEV dans queue 200"
    echo "Done."
else
    echo "Rien à créer."
fi
