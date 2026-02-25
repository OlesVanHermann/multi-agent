# Triangle 200 — Explorer (nettoyage données brutes)

## Agents

```
prompts/200/
├── 200-system.md                     # Explorer : raw/ → clean/ (nettoyage)
├── 200-memory.md                     # INPUT : raw/ fichiers bruts
├── 200-methodology.md                # OUTPUT : clean/ fichiers markdown
│
├── 200-500-system.md                 # Observer : évalue la qualité du nettoyage
├── 200-500-memory.md                 # INPUT : clean/ + critères 200-system.md
├── 200-500-methodology.md            # OUTPUT : bilans/200-cycleN.md
│
├── 200-700-system.md                 # Curator : prépare le contexte pour l'explorer
├── 200-700-memory.md                 # INPUT : raw/ (inventaire fichiers)
├── 200-700-methodology.md            # OUTPUT : 200-memory.md
│
├── 200-800-system.md                 # Coach : améliore les méthodes de nettoyage
├── 200-800-memory.md                 # INPUT : bilans/200-cycleN.md
├── 200-800-methodology.md            # OUTPUT : 200-methodology.md
│
├── 200-900-system.md                 # Tri.Arch : écrit les contrats du triangle
├── 200-900-memory.md                 # INPUT : 000-memory.md
└── 200-900-methodology.md            # OUTPUT : 200-*-system.md + 200-*-memory.md
```

## Pipeline — 7 cycles (0-6)

### Cycle 0 — Bootstrap

```
200-900  lit 000-memory.md → écrit tous les 200-*-system.md + 200-*-memory.md
```

### Cycle 1 — Premier passage

```
200-700  lit raw/ inventaire                   → écrit 200-memory.md
200      lit raw/ + memory + methodology       → écrit clean/
200-500  lit clean/                             → écrit bilans/200-cycle1.md
```

Résultat typique : **60%**

### Cycles 2-5 — Boucles courtes

```
200-800  lit bilans/200-cycleN.md              → améliore 200-methodology.md
200-700  lit raw/ inventaire                   → met à jour 200-memory.md
200      lit raw/ + memory + methodology       → écrit clean/ amélioré
200-500  lit clean/                             → écrit bilans/200-cycleN+1.md
```

### Cycle 6 — Stop

Score stable sur 2 cycles → stop.

## Progression

| Cycle | Score | Ce qui change |
|-------|-------|---------------|
| 0 | — | Bootstrap : 200-900 écrit tous les system.md + memory.md |
| 1 | 60% | Premier nettoyage, métadonnées basiques |
| 2 | 82% | Coach 200-800 améliore les règles de nettoyage |
| 3 | 95% | Coach affine, curator enrichit memory |
| 4 | 97% | Raffinements mineurs |
| 5 | 98% | Quasi-convergence |
| 6 | 98% | Score stable sur 2 cycles → stop |
