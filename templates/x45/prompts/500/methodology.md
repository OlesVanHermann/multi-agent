# 500 — Methodology

## Structure d'un bilan
```markdown
# Bilan {ID} — {date}

## Agent observé
- ID : {agent_id}
- Tâche : {description}
- Maillon : {position dans la chaîne}

## INPUT reçu
- Source : {d'où vient l'input}
- Qualité : {évaluation 1-10}

## OUTPUT produit
- Destination : {où va l'output}
- Complétude : {% des critères de succès remplis}
- Qualité : {évaluation 1-10}

## Métriques
- Temps d'exécution : {durée}
- Tokens consommés : {nombre}
- Erreurs : {nombre et type}
- Tentatives : {nombre}

## Diagnostic
- OK | DÉGRADÉ | ÉCHEC
- Cause probable : {si dégradé ou échec}
- Récurrent : OUI/NON (si oui, depuis combien de cycles)

## Recommandation
- AUCUNE | AJUSTER_METHODOLOGY | RÉÉCRIRE_SYSTEM
```

## Critères d'alerte
- Agent silencieux > 10 minutes → alerte
- Même erreur 3 cycles de suite → alerte + flag "récurrent"
- OUTPUT vide ou corrompu → alerte immédiate
- Score qualité < 4/10 → alerte

## Cycle d'observation
1. Attendre `agent:{ID}:status` = "done" sur Redis
2. Lire le OUTPUT produit
3. Comparer avec les critères de succès du system.md de l'agent
4. Écrire le bilan
5. Publier `bilans:ready`
6. Si alerte, publier `alert:{ID}`
