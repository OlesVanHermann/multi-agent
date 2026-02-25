# Triangle 342 — Dev Synthèse (spec technique)

## Agents

```
prompts/342/
├── 342-system.md                     # Synthèse : rapports 341 → pipeline/342-output/ (spec)
├── 342-memory.md                     # INPUT : pipeline/341-output/
├── 342-methodology.md                # OUTPUT : pipeline/342-output/
│
├── 342-500-system.md                 # Observer : évalue la qualité de la spec
├── 342-500-memory.md                 # INPUT : pipeline/342-output/
├── 342-500-methodology.md            # OUTPUT : bilans/342-cycleN.md
│
├── 342-700-system.md                 # Curator : prépare le contexte pour la synthèse
├── 342-700-memory.md                 # INPUT : pipeline/341-output/ + bilans/
├── 342-700-methodology.md            # OUTPUT : 342-memory.md
│
├── 342-800-system.md                 # Coach : améliore les méthodes de synthèse
├── 342-800-memory.md                 # INPUT : bilans/342-cycleN.md
├── 342-800-methodology.md            # OUTPUT : 342-methodology.md
│
├── 342-900-system.md                 # Tri.Arch : écrit les contrats du triangle
├── 342-900-memory.md                 # INPUT : 000-memory.md
└── 342-900-methodology.md            # OUTPUT : 342-*-system.md + 342-*-memory.md
```

## Pipeline — 7 cycles (0-6)

### Cycle 0 — Bootstrap

```
342-900  lit 000-memory.md → écrit tous les 342-*-system.md + 342-*-memory.md
```

### Cycle 1 — Premier passage

```
342-700  lit pipeline/341-output/ + bilans/    → écrit 342-memory.md
342      lit memory + methodology               → écrit pipeline/342-output/
342-500  lit pipeline/342-output/              → écrit bilans/342-cycle1.md
```

Résultat typique : **60%**

### Cycles 2-5 — Boucles courtes

```
342-800  lit bilans/342-cycleN.md              → améliore 342-methodology.md
342-700  lit pipeline/341-output/ + bilans/    → met à jour 342-memory.md
342      lit memory + methodology               → écrit pipeline/342-output/
342-500  lit pipeline/342-output/              → écrit bilans/342-cycleN+1.md
```

### Cycle 6 — Stop

Score stable sur 2 cycles → stop.

## Progression

| Cycle | Score | Ce qui change |
|-------|-------|---------------|
| 0 | — | Bootstrap : 342-900 écrit tous les system.md + memory.md |
| 1 | 60% | Première spec, structure basique |
| 2 | 82% | Coach 342-800 ajoute règles depuis bilan cycle 1 |
| 3 | 95% | Coach affine, curator enrichit memory |
| 4 | 97% | Raffinements mineurs |
| 5 | 98% | Quasi-convergence |
| 6 | 98% | Score stable sur 2 cycles → stop |
