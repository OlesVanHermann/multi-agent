# x45-complet : MCP Server LibreOffice Calc (15 agents, 3 triangles)

Serveur MCP Python pour manipuler LibreOffice Calc via le bridge UNO.
Fonction implémentée : `set_cell_background_color(sheet_name, cell_address, color)`

## 6 cycles de feedback

| Cycle | 341 (Analyste) | 342 (Synthèse) | 345 (Développeur) |
|-------|----------------|-----------------|-------------------|
| 1 | 75% | 80% | 60% |
| 2 | 90% | 90% | 82% |
| 3 | 95% | 95% | 95% |
| 4-6 | Stabilisation et affinement |

## Agents (15)

| ID | Rôle | Format |
|----|------|--------|
| 900 | Architect Global | monogent |
| 945 | Triangle Architect | monogent |
| 200 | Data Prep | monogent |
| 500 | Observer | monogent |
| 600 | Indexer | monogent |
| 800 | Coach global | monogent |
| 341 | Analyste (fiches) | triangle |
| 741 | Curator de 341 | triangle |
| 841 | Coach de 341 | triangle |
| 342 | Synthèse (specs) | triangle |
| 742 | Curator de 342 | triangle |
| 842 | Coach de 342 | triangle |
| 345 | Développeur (code) | triangle |
| 745 | Curator de 345 | triangle |
| 845 | Coach de 345 | triangle |

## Structure

```
4-x45-complet/
├── README.md
├── prompts/
│   ├── AGENT.md                ← règles communes (pour triangles)
│   ├── 200.md                  ← monogent : Data Prep
│   ├── 500.md                  ← monogent : Observer
│   ├── 600.md                  ← monogent : Indexer
│   ├── 800.md                  ← monogent : Coach global
│   ├── 900.md                  ← monogent : Architect Global
│   ├── 945.md                  ← monogent : Triangle Architect
│   ├── 341/ 741/ 841/          ← Triangle 1 (Analyste)
│   ├── 342/ 742/ 842/          ← Triangle 2 (Synthèse)
│   └── 345/ 745/ 845/          ← Triangle 3 (Développeur)
└── project/
    ├── raw/                    ← 3 fichiers source (UNO API, MCP spec, exemple)
    ├── clean/                  ← Output 200 (markdown structuré)
    ├── index/                  ← Output 600 (chunks.jsonl)
    ├── pipeline/
    │   ├── 341-output/         ← Fiches d'analyse
    │   ├── 342-output/         ← Spec technique
    │   └── output-final/       ← mcp_libreoffice_calc.py (95%)
    └── bilans/                 ← 18 bilans (3 agents × 6 cycles)
```

## Comment lancer

```bash
# 1. Copier l'exemple
cp -r examples/4-x45-complet/prompts/ prompts/
cp -r examples/4-x45-complet/project/ project/

# 2. Lancer l'infra
./scripts/infra.sh start

# 3. Démarrer tous les agents
./scripts/agent.sh start all

# 4. Lancer le pipeline
./scripts/send.sh 200 "go"
```

## Différences avec x45-simple

| Aspect | x45-simple | x45-complet |
|--------|------------|-------------|
| Agents | 7 | 15 |
| Triangles | 1 (341) | 3 (341, 342, 345) |
| Chaînage | Non | Oui (341→342→345) |
| Cycles | 3 | 6 |
| Format infra | monogent | monogent |
| Format workers | triangle | triangle |
