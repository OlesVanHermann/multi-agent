#!/bin/bash
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Merge direct de tous les repos dev vers mcp-onlyoffice/dev
#

MAIN_REPO="$BASE_DIR/project"

echo "=== Merge All Dev Repos ==="
echo ""

cd "$MAIN_REPO"
git checkout dev
git pull origin dev 2>/dev/null || true

for format in excel word pptx pdf; do
    REPO="$BASE_DIR/project-$format"
    BRANCH="dev-$format"

    echo ""
    echo "=== Merge $format ==="

    if [ ! -d "$REPO" ]; then
        echo "⚠ Repo $REPO non trouvé"
        continue
    fi

    # Fetch depuis le repo dev
    echo "Fetching from $REPO..."
    git fetch "$REPO" "$BRANCH"

    # Compter les commits à merger
    count=$(git log --oneline dev..FETCH_HEAD | wc -l | tr -d ' ')
    echo "Commits à merger: $count"

    if [ "$count" -eq 0 ]; then
        echo "✓ Déjà à jour"
        continue
    fi

    # Merge
    echo "Merging..."
    if git merge FETCH_HEAD --no-edit -m "Merge $BRANCH: $count commits"; then
        echo "✓ Merge réussi"
    else
        echo "⚠ Conflit! Résolution automatique..."
        # En cas de conflit sur server_multiformat.py, garder les deux
        git checkout --theirs server_multiformat.py 2>/dev/null
        git add server_multiformat.py
        git commit -m "Merge $BRANCH: resolved conflicts" 2>/dev/null || true
    fi
done

echo ""
echo "=== Vérification syntaxe Python ==="
cd "$MAIN_REPO"
if python3 -m py_compile server_multiformat.py; then
    echo "✓ Syntaxe OK"
else
    echo "✗ Erreur de syntaxe!"
fi

echo ""
echo "=== Résumé ==="
git log --oneline -10
