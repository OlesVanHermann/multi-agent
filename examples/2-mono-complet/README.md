# mono-complet : 10 agents mono, toute la hiérarchie

Un pipeline standard complet avec les 7 niveaux de la hiérarchie.

## But

Montrer le pipeline monogent à pleine échelle :
- 10 agents couvrant tous les rôles
- 3 Developers travaillant en parallèle (Excel, Word, PPTX)
- Flux complet : analyse → dispatch → code → merge → test → release

## Agents

| ID | Rôle | Type | Description |
|----|------|------|-------------|
| 000 | Architect | Configuration | Configure le système |
| 010 | Super-Master | Coordination | Coordination multi-projets |
| 100 | Master | Dispatch | Distribue les tâches aux Developers |
| 200 | Explorer | Analyse | Analyse le projet, crée les SPECs |
| 300 | Dev Excel | Code | Implémente les fonctions Excel |
| 301 | Dev Word | Code | Implémente les fonctions Word |
| 302 | Dev PPTX | Code | Implémente les fonctions PPTX |
| 400 | Integrator | Merge | Cherry-pick et merge Git |
| 500 | Tester | QA | Tests unitaires et intégration |
| 600 | Releaser | Publication | Release et déploiement |

## Structure

```
2-mono-complet/
├── README.md
└── prompts/
    ├── 000.md
    ├── 010.md
    ├── 100.md
    ├── 200.md
    ├── 300.md
    ├── 301.md
    ├── 302.md
    ├── 400.md
    ├── 500.md
    └── 600.md
```

## Comment lancer

```bash
# 1. Copier les prompts dans votre projet
cp -r examples/2-mono-complet/prompts/ prompts/

# 2. Adapter les variables $PROJECT et $BASE dans les prompts

# 3. Lancer l'infra + Architect
./scripts/infra.sh start

# 4. Démarrer tous les agents
./scripts/agent.sh start all

# 5. Lancer le pipeline
./scripts/send.sh 200 "go"
```

## Différences avec mono-simple

| Aspect | mono-simple | mono-complet |
|--------|----------------|------------------|
| Agents | 3 | 10 |
| Hiérarchie | Minimale (000→100→300) | Complète (7 niveaux) |
| Parallélisme | Non | Oui (3 Developers) |

Pour un pipeline avec feedback automatique, voir le mode x45 : `../3-x45-simple/`.
