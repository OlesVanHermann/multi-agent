# 945 — Methodology

## Penser de droite à gauche
Toujours partir du OUTPUT final attendu et remonter la chaîne.
Ne jamais commencer par les données brutes.

## Écriture d'un system.md
Chaque system.md suit ce template :
```
# {ID} — {Rôle}

## Contrat
Une phrase : ce que l'agent fait.

## INPUT
- Source 1 (format, provenance)
- Source 2 (format, provenance)

## OUTPUT
- Destination 1 (format, où ça va)

## Critères de succès
- Critère mesurable 1
- Critère mesurable 2

## Ce que tu NE fais PAS
- Interdit 1
- Interdit 2
```

## Règles de cohérence
- Le OUTPUT d'un agent doit correspondre exactement au INPUT de son consommateur
- Les formats doivent être explicites (markdown, JSON, branche git...)
- Chaque agent a au maximum 3 sources INPUT
- Chaque agent a au maximum 2 destinations OUTPUT
- Si un agent a plus de 3 INPUT → le découper en deux maillons

## Boucle longue — quand réécrire
- 3 cycles consécutifs avec le même type d'échec → réécrire
- Score moyen des bilans < 60% → réécrire
- Un 8XX signale qu'il ne peut plus améliorer la methodology → réécrire
- Toujours logger : date, agent concerné, ancien contrat, nouveau contrat, raison

## Budget tokens
- system.md : 50 lignes max
- Pas de prose, pas de contexte. Juste le contrat.
