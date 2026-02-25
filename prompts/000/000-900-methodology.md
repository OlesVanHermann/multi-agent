# 000-900 — Methodology

## Penser de droite à gauche
Toujours partir du rôle de 000 (configurer les triangles)
et remonter vers ce dont chaque agent satellite a besoin.

## Écriture d'un system.md
Chaque system.md suit ce template :
```
# {ID} — {Rôle}

## Contrat
Une phrase : ce que l'agent fait.

## INPUT
- Source 1 (format, provenance)

## OUTPUT
- Destination 1 (format, où ça va)

## Critères de succès
- Critère mesurable 1
- Critère mesurable 2

## Ce que tu NE fais PAS
- Interdit 1
```

## Règles de cohérence
- Le OUTPUT d'un agent = INPUT de son consommateur
- Formats explicites (markdown, JSON, Redis event)
- Max 3 INPUT, max 2 OUTPUT par agent
- system.md : 50 lignes max

## Boucle longue
- 3 cycles consécutifs même échec → réécrire system.md
- Score moyen < 60% → réécrire
- Logger : date, agent, ancien contrat, nouveau contrat, raison
