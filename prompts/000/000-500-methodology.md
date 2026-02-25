# 000-500 — Methodology

## Étapes
1. Lire la configuration produite par 000
2. Vérifier la cohérence de la chaîne pipeline
3. Évaluer chaque métrique (0-100%) :
   - Cohérence : pas de trou dans la chaîne
   - Complétude : tous les triangles sont là
   - Clarté : contrats non ambigus
   - Performance : scores en progression
4. Calculer le score global (moyenne pondérée)
5. Lister les problèmes avec exemples concrets
6. Écrire le bilan dans `bilans/000-cycle{N}.md`
7. Publier `bilans:ready` sur Redis
