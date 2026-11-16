# 341-500 — Methodology

## Étapes
1. Lire le rapport de 341 dans `project/pipeline/341-output/`
2. Relire le system.md de 341 pour les critères de succès
3. Évaluer chaque métrique (0-100%) :
   - Complétude : toutes les colonnes CSV exploitées ?
   - Exactitude : les chiffres sont corrects ?
   - Structure : le format est respecté ?
   - Actionnabilité : les recommandations sont concrètes ?
4. Calculer le score global (moyenne pondérée)
5. Lister les problèmes avec exemples concrets
6. Écrire le bilan dans `project/bilans/341-cycle{N}.md`
7. Publier `bilans:ready` sur Redis
