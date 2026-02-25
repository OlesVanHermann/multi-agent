# 345-900 — Methodology

## Penser de droite à gauche
Partir du code attendu par 345 et remonter vers
ce dont chaque satellite a besoin.

## Écriture d'un system.md
Template standard :
# {ID} — {Rôle}
## Contrat / ## INPUT / ## OUTPUT / ## Critères de succès / ## Ce que tu NE fais PAS

## Règles de cohérence
- OUTPUT d'un agent = INPUT de son consommateur
- Formats explicites
- Max 3 INPUT, max 2 OUTPUT
- system.md : 50 lignes max

## Boucle longue
- 3 cycles même échec → réécrire
- Score < 60% → réécrire
- Logger chaque changement
