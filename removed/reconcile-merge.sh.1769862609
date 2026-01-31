#!/bin/bash
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
# Réconciliation: Injecter les commits non mergés dans la queue 400
#

MAIN_REPO="$BASE_DIR/project"

echo "=== Réconciliation Merge ==="
echo ""

# Pour chaque format
for format in excel word pptx pdf; do
    REPO="$BASE_DIR/project-$format"
    BRANCH="dev-$format"

    case $format in
        excel) FORMAT_UPPER="Excel" ;;
        word)  FORMAT_UPPER="Word" ;;
        pptx)  FORMAT_UPPER="PPTX" ;;
        pdf)   FORMAT_UPPER="PDF" ;;
    esac

    if [ ! -d "$REPO" ]; then
        echo "⚠ Repo $REPO non trouvé"
        continue
    fi

    echo "Traitement $FORMAT_UPPER..."

    cd "$REPO"

    # Lister les commits sur la branche dev-xxx
    # On prend les commits qui ont un message feat() ou fix()
    commits=$(git log --oneline "$BRANCH" --grep="feat\|fix" | head -200)

    count=0
    while IFS= read -r line; do
        [ -z "$line" ] && continue

        hash=$(echo "$line" | awk '{print $1}')
        msg=$(echo "$line" | cut -d' ' -f2-)

        # Extraire le nom de la fonction du message
        func=$(echo "$msg" | grep -oE "${format}_[a-z_]+" | head -1)
        [ -z "$func" ] && func="unknown"

        # Créer le message pour 400
        notify_msg="$FORMAT_UPPER commit: $hash - $func"

        # Injecter dans la queue 400
        redis-cli RPUSH "ma:inject:400" "$notify_msg" > /dev/null

        count=$((count + 1))
    done <<< "$commits"

    echo "  → $count commits injectés pour $FORMAT_UPPER"
done

echo ""
echo "Queue 400: $(redis-cli LLEN 'ma:inject:400') messages"
echo ""
echo "Done. Agent 400 va traiter les merges."
