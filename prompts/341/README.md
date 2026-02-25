# Triangle 341 — Dev Analyste (rapport structuré)

## Agents

```
prompts/341/
├── 341-system.md                     # Analyste : clean/ → pipeline/341-output/ (rapport)
├── 341-memory.md                     # INPUT : clean/ + index/
├── 341-methodology.md                # OUTPUT : pipeline/341-output/
│
├── 341-500-system.md                 # Observer : évalue la qualité du rapport
├── 341-500-memory.md                 # INPUT : pipeline/341-output/
├── 341-500-methodology.md            # OUTPUT : bilans/341-cycleN.md
│
├── 341-700-system.md                 # Curator : prépare le contexte pour l'analyste
├── 341-700-memory.md                 # INPUT : index/ + bilans/
├── 341-700-methodology.md            # OUTPUT : 341-memory.md
│
├── 341-800-system.md                 # Coach : améliore les méthodes d'analyse
├── 341-800-memory.md                 # INPUT : bilans/341-cycleN.md
├── 341-800-methodology.md            # OUTPUT : 341-methodology.md
│
├── 341-900-system.md                 # Tri.Arch : écrit les contrats du triangle
├── 341-900-memory.md                 # INPUT : 000-memory.md
└── 341-900-methodology.md            # OUTPUT : 341-*-system.md + 341-*-memory.md
```

## Pipeline — 7 cycles (0-6)

### Cycle 0 — Bootstrap

```
341-900  lit 000-memory.md → écrit tous les 341-*-system.md + 341-*-memory.md
```

### Cycle 1 — Premier passage

```
341-700  lit index/ + bilans/                  → écrit 341-memory.md
341      lit clean/ + memory + methodology     → écrit pipeline/341-output/
341-500  lit pipeline/341-output/              → écrit bilans/341-cycle1.md
```

Résultat typique : **60%**

### Cycles 2-5 — Boucles courtes

```
341-800  lit bilans/341-cycleN.md              → améliore 341-methodology.md
341-700  lit index/ + bilans/                  → met à jour 341-memory.md
341      lit clean/ + memory + methodology     → écrit pipeline/341-output/
341-500  lit pipeline/341-output/              → écrit bilans/341-cycleN+1.md
```

### Cycle 6 — Stop

Score stable sur 2 cycles → stop.

## Progression

| Cycle | Score | Ce qui change |
|-------|-------|---------------|
| 0 | — | Bootstrap : 341-900 écrit tous les system.md + memory.md |
| 1 | 60% | Premier rapport, analyse basique |
| 2 | 82% | Coach 341-800 ajoute règles depuis bilan cycle 1 |
| 3 | 95% | Coach affine, curator enrichit memory |
| 4 | 97% | Raffinements mineurs |
| 5 | 98% | Quasi-convergence |
| 6 | 98% | Score stable sur 2 cycles → stop |
