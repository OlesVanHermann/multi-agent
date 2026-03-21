# pipeline-simple : 3 agents monogent

Le format monogent le plus simple : un fichier `{ID}.md` par agent.

## But

Montrer le format de base d'un prompt monogent :
- Un fichier `prompts/{ID}.md` = un agent
- Chaque fichier contient 3 sections : Contrat, Memory, Methodology
- Hiérarchie minimale : Architect → Master → Developer

## Structure

```
1-pipeline-simple/
├── README.md
└── prompts/
    ├── 000.md    ← configure, supervise
    ├── 100.md    ← dispatch au developer
    └── 300.md    ← implémente le code
```

## Format monogent

```markdown
# {ID} — {Rôle}

## Contrat
Ce que l'agent fait. IN/OUT.

---

## Memory
Contexte curé pour la tâche en cours.

---

## Methodology
Comment exécuter le contrat avec le contexte.
```

Chaque agent est autonome : il reçoit des messages via Redis, exécute son workflow, et notifie les agents suivants.

## Comment lancer

```bash
# 1. Copier les prompts dans votre projet
cp -r examples/1-pipeline-simple/prompts/ prompts/

# 2. Lancer l'infra
./scripts/infra.sh start

# 3. Démarrer les agents
./scripts/agent.sh start all

# 4. Lancer le pipeline
./scripts/send.sh 000 "go"
```

## Différences avec le mode x45

| Aspect | Monogent (flat) | x45 (triangle) |
|--------|-----------------|-----------------|
| Fichiers | 1 par agent ({ID}.md) | 16 par triangle (répertoire) |
| Sections | Contrat + Memory + Methodology | system.md + memory.md + methodology.md + satellites |
| Feedback | Non | Oui (Observer + Coach) |
| Amélioration | Manuelle | Automatique |

Pour voir un pipeline complet avec toute la hiérarchie, voir `../2-pipeline-complet/`.
