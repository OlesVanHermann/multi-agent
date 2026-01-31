#!/bin/bash
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Réconciliation: Créer les PR-TEST manquants pour les PR-SPEC done
#

PR_DIR="$BASE_DIR/pool-requests"
NEXT_ID_FILE="$PR_DIR/NEXT_ID"

echo "=== Réconciliation PR-SPEC → PR-TEST ==="
echo ""

# Compteurs
created=0
skipped=0
errors=0

# Pour chaque PR-SPEC dans done/
for spec_file in "$PR_DIR"/done/PR-SPEC-*.md; do
    [ -f "$spec_file" ] || continue

    # Extraire l'agent et l'ID du nom de fichier
    basename=$(basename "$spec_file" .md)
    # PR-SPEC-300-123 → agent=300, id=123
    agent=$(echo "$basename" | sed 's/PR-SPEC-\([0-9]*\)-.*/\1/')
    old_id=$(echo "$basename" | sed 's/PR-SPEC-[0-9]*-//')

    # Vérifier si un PR-TEST existe déjà (pending, assigned ou done)
    if ls "$PR_DIR"/pending/PR-TEST-${agent}-*.md 2>/dev/null | grep -q "PR-TEST-${agent}-${old_id}"; then
        ((skipped++))
        continue
    fi
    if ls "$PR_DIR"/assigned/PR-TEST-${agent}-*.md 2>/dev/null | grep -q "PR-TEST-${agent}-${old_id}"; then
        ((skipped++))
        continue
    fi
    if ls "$PR_DIR"/done/PR-TEST-${agent}-*.md 2>/dev/null | grep -q "PR-TEST-${agent}-${old_id}"; then
        ((skipped++))
        continue
    fi

    # Extraire les infos du PR-SPEC
    spec_ref=$(grep "^## Spec file" "$spec_file" -A1 | tail -1 | tr -d ' ')
    if [ -z "$spec_ref" ]; then
        spec_ref=$(grep "SPEC-" "$spec_file" | head -1 | grep -o "SPEC-[A-Z]*-[a-z_]*\.md" || echo "unknown")
    fi

    # Extraire la fonction du COMPLETED section ou du nom
    fonction=$(grep "^\*\*Fonction:\*\*" "$spec_file" | head -1 | sed 's/.*\*\*Fonction:\*\* //')
    if [ -z "$fonction" ]; then
        # Essayer d'extraire du spec_ref
        fonction=$(echo "$spec_ref" | sed 's/SPEC-[A-Z]*-//' | sed 's/\.md//')
    fi

    # Extraire le commit
    commit=$(grep "^\*\*Commit:\*\*" "$spec_file" | head -1 | sed 's/.*\*\*Commit:\*\* //')

    # Créer le PR-TEST avec le même ID
    cat > "$PR_DIR/pending/PR-TEST-${agent}-${old_id}.md" << EOF
# PR-TEST-${agent}-${old_id}

## Ref
PR-SPEC-${agent}-${old_id}

## Spec file
${spec_ref}

## Fonction
${fonction}

## Commit
${commit:-unknown}

## Agent cible
501 (Test Creator)

## Date
$(date +%Y-%m-%d)

## Note
Créé par réconciliation (PR-SPEC existant sans PR-TEST)
EOF

    ((created++))
done

echo "Résultat:"
echo "  Créés:  $created"
echo "  Skippés (déjà existant): $skipped"
echo ""

if [ "$created" -gt 0 ]; then
    echo "Commit des nouveaux PR-TEST..."
    cd "$PR_DIR"
    git add pending/PR-TEST-*.md
    git commit -m "reconcile: created $created missing PR-TEST"

    echo ""
    echo "Injection dans la queue 501..."
    for f in "$PR_DIR"/pending/PR-TEST-*.md; do
        pr=$(basename "$f" .md)
        redis-cli RPUSH "ma:inject:501" "$pr" > /dev/null
    done
    echo "Done."
fi
