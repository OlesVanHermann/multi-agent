# 100-900 — Methodology

## Penser de droite à gauche
Partir du rôle de 100 (orchestrer le pipeline)
et remonter vers ce dont chaque agent satellite a besoin.

## Écriture d'un system.md
Chaque system.md suit le template standard :
# {ID} — {Rôle}
## Contrat / ## INPUT / ## OUTPUT / ## Critères de succès / ## Ce que tu NE fais PAS

## Règles de cohérence
- OUTPUT d'un agent = INPUT de son consommateur
- Formats explicites
- Max 3 INPUT, max 2 OUTPUT
- system.md : 50 lignes max

## Boucle longue
- 3 cycles même échec → réécrire system.md
- Score < 60% → réécrire
- Logger chaque changement
