# Triangle 100 — Master (orchestration pipeline)

## Agents

```
prompts/100/
├── 100-system.md                     # Master : orchestre le pipeline, dispatch aux workers
├── 100-memory.md                     # INPUT : project-config.md + état pipeline
├── 100-methodology.md                # OUTPUT : dispatch via Redis + suivi avancement
│
├── 100-500-system.md                 # Observer : évalue l'orchestration
├── 100-500-memory.md                 # INPUT : bilans/ + logs/
├── 100-500-methodology.md            # OUTPUT : bilans/100-cycleN.md
│
├── 100-700-system.md                 # Curator : prépare le contexte d'orchestration
├── 100-700-memory.md                 # INPUT : project-config.md + état agents
├── 100-700-methodology.md            # OUTPUT : 100-memory.md
│
├── 100-800-system.md                 # Coach : améliore la méthode d'orchestration
├── 100-800-memory.md                 # INPUT : bilans/100-cycleN.md
├── 100-800-methodology.md            # OUTPUT : 100-methodology.md
│
├── 100-900-system.md                 # Tri.Arch : écrit les contrats du triangle
├── 100-900-memory.md                 # INPUT : 000-memory.md
└── 100-900-methodology.md            # OUTPUT : 100-*-system.md + 100-*-memory.md
```

## Pipeline — 7 cycles (0-6)

### Cycle 0 — Bootstrap

```
100-900  lit 000-memory.md → écrit tous les 100-*-system.md + 100-*-memory.md
```

### Cycle 1 — Premier passage

```
100-700  lit project-config.md + état agents   → écrit 100-memory.md
100      lit memory + methodology               → dispatch pipeline
100-500  lit bilans/ + logs/                    → écrit bilans/100-cycle1.md
```

Résultat typique : **60%**

### Cycles 2-5 — Boucles courtes

```
100-800  lit bilans/100-cycleN.md              → améliore 100-methodology.md
100-700  lit project-config.md + état agents   → met à jour 100-memory.md
100      lit memory + methodology               → dispatch amélioré
100-500  lit bilans/ + logs/                    → écrit bilans/100-cycleN+1.md
```

### Cycle 6 — Stop

Score stable sur 2 cycles → stop.

## Progression

| Cycle | Score | Ce qui change |
|-------|-------|---------------|
| 0 | — | Bootstrap : 100-900 écrit tous les system.md + memory.md |
| 1 | 60% | Premier dispatch, orchestration basique |
| 2 | 82% | Coach 100-800 améliore les règles de dispatch |
| 3 | 95% | Coach affine, curator enrichit memory |
| 4 | 97% | Raffinements mineurs |
| 5 | 98% | Quasi-convergence |
| 6 | 98% | Score stable sur 2 cycles → stop |
