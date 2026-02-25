# Triangle 345 — Dev (implémentation code)

## Agents

```
prompts/345/
├── 345-system.md                     # Dev : implémente le code selon spec
├── 345-memory.md                     # INPUT : clean/ + 345-memory.md
├── 345-methodology.md                # OUTPUT : pipeline/345-output/
│
├── 345-500-system.md                 # Observer : évalue la qualité du code produit
├── 345-500-memory.md                 # INPUT : pipeline/345-output/
├── 345-500-methodology.md            # OUTPUT : bilans/345-cycleN.md
│
├── 345-700-system.md                 # Curator : prépare le contexte pour le dev
├── 345-700-memory.md                 # INPUT : index/ + bilans/345-cycleN.md
├── 345-700-methodology.md            # OUTPUT : 345-memory.md
│
├── 345-800-system.md                 # Coach : améliore les méthodes de travail du dev
├── 345-800-memory.md                 # INPUT : bilans/345-cycleN.md
├── 345-800-methodology.md            # OUTPUT : 345-methodology.md
│
├── 345-900-system.md                 # Tri.Arch : écrit les contrats de chaque agent
├── 345-900-memory.md                 # INPUT : 000-memory.md
└── 345-900-methodology.md            # OUTPUT : 345-*-system.md + 345-*-memory.md (cycle 0)
```

## Pipeline — 7 cycles (0-6)

### Cycle 0 — Bootstrap

```
345-900  lit 000-memory.md → écrit tous les 345-*-system.md + 345-*-memory.md
```

### Cycle 1 — Premier passage

```
345-700  lit index/ + bilans/                → écrit 345-memory.md
345      lit clean/ + memory + methodology   → écrit pipeline/345-output/
345-500  lit pipeline/345-output/            → écrit bilans/345-cycle1.md
```

Résultat typique : **60%**

### Cycle 2 — Boucle courte

```
345-800  lit bilans/345-cycle1.md            → améliore 345-methodology.md
345-700  lit index/ + bilans/                → met à jour 345-memory.md
345      lit clean/ + memory + methodology   → écrit pipeline/345-output/
345-500  lit pipeline/345-output/            → écrit bilans/345-cycle2.md
```

Résultat typique : **82%**

### Cycle 3 — Boucle courte

```
345-800  lit bilans/345-cycle2.md            → améliore 345-methodology.md
345-700  lit index/ + bilans/                → met à jour 345-memory.md
345      lit clean/ + memory + methodology   → écrit pipeline/345-output/
345-500  lit pipeline/345-output/            → écrit bilans/345-cycle3.md
```

Résultat typique : **95%**

### Cycles 4-5 — Convergence

```
345-800  lit bilans/345-cycleN.md            → raffinements mineurs methodology
345-700  lit index/ + bilans/                → met à jour 345-memory.md
345      lit clean/ + memory + methodology   → écrit pipeline/345-output/
345-500  lit pipeline/345-output/            → écrit bilans/345-cycleN.md
```

Résultat typique : **97% → 98%**

### Cycle 6 — Stop

```
345-800  lit bilans/345-cycle5.md            → rien à améliorer
345-700  lit index/ + bilans/                → met à jour 345-memory.md
345      lit clean/ + memory + methodology   → écrit pipeline/345-output/
345-500  lit pipeline/345-output/            → écrit bilans/345-cycle6.md → 98% = 98% → stop
```

## Progression

| Cycle | Score | Ce qui change |
|-------|-------|---------------|
| 0 | — | Bootstrap : 345-900 écrit tous les system.md + memory.md |
| 1 | 60% | Premier passage, methodology basique |
| 2 | 82% | Coach 345-800 ajoute règles depuis bilan cycle 1 |
| 3 | 95% | Coach 345-800 affine, curator 345-700 enrichit memory |
| 4 | 97% | Raffinements mineurs |
| 5 | 98% | Quasi-convergence |
| 6 | 98% | Score stable sur 2 cycles → stop |

## Boucle courte vs boucle longue

- **Boucle courte** (cycles 2-6) : 345-500 observe → 345-800 améliore methodology → 345 exécute mieux
- **Boucle longue** (si nécessaire) : 345-500 observe → 345-900 réécrit system.md → tous se reconfigurent

En pratique, la boucle courte suffit pour passer de 60% à 98%. La boucle longue n'est déclenchée que si la methodology ne peut plus s'améliorer et le score stagne.
