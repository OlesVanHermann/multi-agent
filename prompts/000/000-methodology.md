# 000 — Methodology

## Étapes
1. Lire l'orientation humaine dans memory.md
2. Identifier les données brutes disponibles dans project/raw/
3. Déterminer la chaîne de traitement :
   - Combien de maillons 3XX nécessaires
   - Quel rôle pour chaque maillon
   - Quel output final attendu
4. Configurer 200 (Data Prep) via son 200-900
5. Configurer chaque triangle 3XX via leurs XXX-900
6. Configurer 100 (Master) avec la vue d'ensemble
7. Vérifier la cohérence bout en bout

## Règles
- Penser de droite à gauche : partir du output final
- Chaque maillon a un INPUT et un OUTPUT typés
- Le OUTPUT d'un maillon = INPUT du suivant
- Ne pas sur-spécifier : laisser les 900 décider du détail
- Documenter dans project-config.md
