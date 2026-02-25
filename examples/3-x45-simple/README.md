# x45-simple : Un triangle complet (7 agents)

Un worker (341) + son curator (741) + son coach (841) = un triangle.
Avec l'infra monogent (900, 945, 200, 500), c'est le pipeline x45 minimal qui boucle.

## But

Montrer le triangle 3XX + 7XX + 8XX avec feedback :
- **741 (Curator)** prépare `341/memory.md` depuis l'index
- **841 (Coach)** améliore `341/methodology.md` depuis les bilans de 500
- **500 (Observer)** évalue les outputs de 341 et produit des bilans
- Les agents infra (900, 945, 200, 500) sont des **monogents** (1 fichier .md)

## Tâche

L'agent 341 analyse un fichier CSV et produit un rapport structuré.

## Structure

```
3-x45-simple/
├── README.md
├── prompts/
│   ├── AGENT.md                 ← règles communes
│   ├── 200.md                   ← monogent : Data Prep (CSV → markdown)
│   ├── 341/                     ← triangle : Worker (analyse CSV)
│   │   ├── 341-system.md
│   │   ├── 341-memory.md        ← écrit par 741
│   │   └── 341-methodology.md   ← amélioré par 841
│   ├── 741/                     ← triangle : Curator de 341
│   │   └── ...
│   └── 841/                     ← triangle : Coach de 341
│       └── ...
└── project/
    ├── raw/                     ← données brutes
    │   └── ventes-2025.csv
    ├── clean/                   ← output 200
    │   └── ventes-2025.md
    ├── pipeline/
    │   └── 341-output/          ← output 341
    │       └── rapport-ventes.md
    └── bilans/                  ← output 500
        └── 341-cycle1.md
```

## Le triangle expliqué

```
         741 Curator                841 Coach
         (prépare memory)          (améliore methodology)
              │                         │
              ▼                         ▼
    ┌─────────────────────┐    ┌─────────────────────────┐
    │  341/memory.md      │    │  341/methodology.md     │
    └─────────┬───────────┘    └────────────┬────────────┘
              │                              │
              └──────────┬───────────────────┘
                         ▼
                ┌─────────────────┐
                │   341 Worker    │
                │  (analyse CSV)  │
                └────────┬────────┘
                         │ output
                         ▼
                ┌─────────────────┐
                │  500 Observer   │
                │  (évalue)       │
                └────────┬────────┘
                         │ bilan
                    ┌────┴────┐
                    ▼         ▼
                  841       945
               (boucle    (boucle
                courte)    longue)
```

## Comment lancer

```bash
# 1. Copier l'exemple
cp -r examples/3-x45-simple/prompts/ prompts/
cp -r examples/3-x45-simple/project/ project/

# 2. Lancer l'infra
./scripts/infra.sh start

# 3. Démarrer les agents
./scripts/agent.sh start all

# 4. Lancer le pipeline
./scripts/send.sh 200 "go"
```

## Progression par cycle

| Cycle | Score 341 | Ce qui change |
|-------|-----------|---------------|
| 1 | 65% | Premier passage, methodology basique |
| 2 | 85% | Coach 841 ajoute des règles depuis le bilan |
| 3 | 95% | Curator 741 enrichit le memory avec plus de contexte |

## Différences avec pipeline-simple

| Aspect | pipeline-simple | x45-simple |
|--------|----------------|------------|
| Format infra | monogent ({ID}.md) | monogent ({ID}.md) |
| Format workers | monogent | triangle (3 fichiers + satellites) |
| Agents | 3 (000, 100, 300) | 7 (200, 500, 341, 741, 841 + 900, 945) |
| Feedback | Non | Oui (boucle courte via 841) |
| Curation | Non | Oui (741 prépare memory.md) |
| Observation | Non | Oui (500 produit des bilans) |

Pour un projet complet avec plusieurs triangles, voir `../4-x45-complet/`.
