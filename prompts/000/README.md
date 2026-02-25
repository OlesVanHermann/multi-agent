# Triangle 000 — Architect (point d'entrée)

## Agents

```
prompts/000/
├── 000-system.md                     # Architect : reçoit orientation, configure triangles
├── 000-memory.md                     # INPUT : orientation humaine + project-config.md
├── 000-methodology.md                # OUTPUT : prompts/100/, prompts/XXX/ (config)
│
├── 000-500-system.md                 # Observer : évalue la cohérence globale
├── 000-500-memory.md                 # INPUT : pipeline/ + bilans/
├── 000-500-methodology.md            # OUTPUT : bilans/000-cycleN.md
│
├── 000-700-system.md                 # Curator : prépare le contexte projet
├── 000-700-memory.md                 # INPUT : project-config.md + docs/
├── 000-700-methodology.md            # OUTPUT : 000-memory.md
│
├── 000-800-system.md                 # Coach : améliore la méthode de l'architecte
├── 000-800-memory.md                 # INPUT : bilans/000-cycleN.md
├── 000-800-methodology.md            # OUTPUT : 000-methodology.md
│
├── 000-900-system.md                 # Tri.Arch : écrit les contrats du triangle
├── 000-900-memory.md                 # INPUT : orientation humaine
└── 000-900-methodology.md            # OUTPUT : 000-*-system.md + 000-*-memory.md
```

## Pipeline — 7 cycles (0-6)

### Cycle 0 — Bootstrap

```
000-900  lit orientation humaine → écrit tous les 000-*-system.md + 000-*-memory.md
```

### Cycle 1 — Premier passage

```
000-700  lit project-config.md + docs/        → écrit 000-memory.md
000      lit memory + methodology              → configure 100 + triangles
000-500  lit pipeline/ + bilans/               → écrit bilans/000-cycle1.md
```

Résultat typique : **60%**

### Cycles 2-5 — Boucles courtes

```
000-800  lit bilans/000-cycleN.md             → améliore 000-methodology.md
000-700  lit project-config.md + docs/        → met à jour 000-memory.md
000      lit memory + methodology              → reconfigure
000-500  lit pipeline/ + bilans/               → écrit bilans/000-cycleN+1.md
```

### Cycle 6 — Stop

Score stable sur 2 cycles → stop.

## Progression

| Cycle | Score | Ce qui change |
|-------|-------|---------------|
| 0 | — | Bootstrap : 000-900 écrit tous les system.md + memory.md |
| 1 | 60% | Premier passage, configuration initiale |
| 2 | 82% | Coach 000-800 ajoute règles depuis bilan cycle 1 |
| 3 | 95% | Coach affine, curator enrichit memory |
| 4 | 97% | Raffinements mineurs |
| 5 | 98% | Quasi-convergence |
| 6 | 98% | Score stable sur 2 cycles → stop |
