#!/bin/bash
# Ajoute un maillon 3XX avec son triangle (7XX curator + 8XX coach)
# Usage: ./scripts/x45-add-agent.sh <id_3xx> <role>
# Exemple: ./scripts/x45-add-agent.sh 343 "Vérification qualité"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
ID="${1:?Usage: $0 <id_3xx> <role>}"
ROLE="${2:?Usage: $0 <id_3xx> <role>}"

# Validate ID is in 3XX range
if [[ ! "$ID" =~ ^3[0-9][0-9]$ ]]; then
    echo "Erreur: l'ID doit être dans la plage 3XX (300-399)" >&2
    exit 1
fi

# Extract corresponding IDs
SUFFIX="${ID:1}"  # ex: 43 de 343
CURATOR="7${SUFFIX}"
COACH="8${SUFFIX}"

echo "=== Création triangle $ID ==="
echo "  3XX: $ID ($ROLE)"
echo "  7XX: $CURATOR (Curator de $ID)"
echo "  8XX: $COACH (Coach de $ID)"

for AGENT_ID in "$ID" "$CURATOR" "$COACH"; do
    DIR="$ROOT/prompts/$AGENT_ID"
    mkdir -p "$DIR"

    # Create AGENT.md symlink
    if [ -f "$ROOT/prompts/AGENT.md" ]; then
        ln -sf ../AGENT.md "$DIR/agent.md"
    fi

    if [ "$AGENT_ID" = "$ID" ]; then
        # 3XX - Developer
        cat > "$DIR/system.md" << EOF
# $AGENT_ID — $ROLE

## Contrat
[À configurer par 945]

## INPUT
- ${AGENT_ID}-memory.md (contexte curé par $CURATOR)
- [output du maillon précédent]

## OUTPUT
- Résultat dans pipeline/${AGENT_ID}-output/
- Événement Redis agent:${AGENT_ID}:done
- Destination : [INPUT du maillon suivant]

## Critères de succès
[À définir par 945]

## Ce que tu NE fais PAS
[À définir par 945]
EOF

        cat > "$DIR/memory.md" << EOF
# $AGENT_ID — Memory

[Curé par $CURATOR]

## Tâche en cours
[Assignée par le pipeline]

## Données pertinentes
[Chunks extraits de l'index par $CURATOR]
EOF

        cat > "$DIR/methodology.md" << EOF
# $AGENT_ID — Methodology

## Process
[À définir. Sera amélioré par $COACH.]

## Changelog
EOF

    elif [ "$AGENT_ID" = "$CURATOR" ]; then
        # 7XX - Curator
        cat > "$DIR/system.md" << EOF
# $CURATOR — Curator de $ID ($ROLE)

## Contrat
Tu prépares le memory.md de l'agent $ID.

## INPUT
- prompts/$ID/system.md
- prompts/$ID/methodology.md
- Tâche assignée à $ID (via Redis)
- INDEX (via fonction search de 600)

## OUTPUT
- prompts/$ID/memory.md mis à jour
- Événement Redis memory:${ID}:ready

## Critères de succès
- memory.md contient les données nécessaires à la tâche
- Budget tokens respecté (max 2000 tokens)
- Pas de bruit

## Ce que tu NE fais PAS
- Tu n'exécutes PAS la tâche de $ID
- Tu n'indexes PAS. C'est 600.
EOF

        cat > "$DIR/memory.md" << EOF
# $CURATOR — Memory

## Agent cible : $ID
## Tâche en cours de $ID
[À remplir]
## État de l'INDEX
[À remplir]
EOF

        cat > "$DIR/methodology.md" << EOF
# $CURATOR — Methodology

## Process de curation
1. Lire system.md et methodology.md de $ID
2. Identifier les données nécessaires
3. Formuler 2-3 requêtes vers INDEX
4. Filtrer par pertinence (score > 0.7)
5. Assembler memory.md (max 2000 tokens)

## Changelog
EOF

    elif [ "$AGENT_ID" = "$COACH" ]; then
        # 8XX - Coach
        cat > "$DIR/system.md" << EOF
# $COACH — Coach de $ID ($ROLE)

## Contrat
Tu améliores la methodology.md de l'agent $ID.

## INPUT
- Bilans 500 concernant $ID (dans bilans/${ID}-*.md)
- prompts/$ID/system.md
- prompts/$ID/methodology.md actuel
- Événement Redis bilans:ready

## OUTPUT
- prompts/$ID/methodology.md amélioré
- Événement Redis methodology:${ID}:updated

## Critères de succès
- Les patterns d'échec sont corrigés
- Chaque changement est loggé
- methodology < 100 lignes

## Ce que tu NE fais PAS
- Tu ne modifies PAS system.md (c'est 945)
- Tu ne modifies PAS memory.md (c'est $CURATOR)
- Si problème de contrat → escalate:945
EOF

        cat > "$DIR/memory.md" << EOF
# $COACH — Memory

## Agent cible : $ID
## Bilans récents
[Extraits des bilans 500]
## Historique améliorations
[Log]
EOF

        cat > "$DIR/methodology.md" << EOF
# $COACH — Methodology

## Process d'amélioration
1. Lire bilans 500 de $ID
2. Identifier échecs
3. Classifier : methodology / memory / system
4. Réécrire section concernée
5. Ajouter au changelog

## Escalade vers 945
Condition : 3 cycles sans amélioration.

## Changelog
EOF
    fi

    echo "  ✓ $AGENT_ID créé (3 fichiers + symlink)"
done

# Create pipeline output directory
mkdir -p "$ROOT/project/pipeline/${ID}-output" 2>/dev/null || true

echo ""
echo "=== Triangle $ID prêt ==="
echo "→ Faire configurer par 945 : ./scripts/x45-run-agent.sh 945"
