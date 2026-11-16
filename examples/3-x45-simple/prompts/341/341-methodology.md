# 341 — Methodology

## Étapes
1. Lire les données nettoyées dans `project/clean/ventes-2025.md`
2. Calculer les métriques globales :
   - Total des ventes, nombre de transactions, période couverte
3. Classer les produits par revenu total (top 5)
4. Analyser les tendances par région :
   - Revenu total par région
   - Évolution mensuelle (croissance/décroissance)
5. Identifier les patterns :
   - Saisonnalité (mois forts/faibles)
   - Corrélations produit-région
6. Rédiger 3+ recommandations actionnables basées sur les données
7. Assembler le rapport dans le format :
   ```
   # Rapport d'analyse des ventes 2025
   ## Résumé exécutif
   ## Top produits
   ## Tendances régionales
   ## Recommandations
   ```
8. Écrire dans `project/pipeline/341-output/rapport-ventes.md`

## Règles
- Chaque chiffre cité doit être traçable dans les données
- Les recommandations doivent citer les données qui les justifient
- Pas de prose générique : aller droit aux chiffres
