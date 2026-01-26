# Multi-Agent System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude](https://img.shields.io/badge/Powered%20by-Claude-blueviolet)](https://claude.ai)

Système d'orchestration multi-agents pour projets de développement complexes avec Claude.

## Caractéristiques

- **Jusqu'à 1000 agents** en parallèle
- **Pipeline structurée** : agents spécialisés avec rôles définis
- **Isolation Git** : chaque développeur travaille dans son propre clone/branche
- **Communication Redis** : coordination temps réel
- **Hiérarchie claire** : Architect → Super-Master → Master → Workers
- **Templates réutilisables** : adaptez facilement à votre projet

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  9XX ARCHITECTS     - Configurent le système                    │
│  0XX SUPER-MASTERS  - Coordination multi-projets                │
│  1XX MASTERS        - Coordination projet                       │
│  2XX EXPLORERS      - Analyse, création SPEC                    │
│  3XX DEVELOPERS     - Implémentation code (parallèle)           │
│  4XX INTEGRATORS    - Merge Git                                 │
│  5XX TESTERS        - Tests, validation                         │
│  6XX RELEASERS      - Publication                               │
└─────────────────────────────────────────────────────────────────┘
```

## Résultats

Ce système a été utilisé pour développer le projet **MCP OnlyOffice** :

| Métrique | Valeur |
|----------|--------|
| Outils MCP créés | 197+ |
| Formats supportés | 4 (Excel, Word, PPTX, PDF) |
| Tests passés | 78/78 |
| Agents en parallèle | 12 |

## Prérequis

- **Docker Desktop** (pour Redis)
- **Python 3.11+**
- **Claude CLI** ([claude-code](https://github.com/anthropics/claude-code))
- **Git**

## Installation

### 1. Cloner le repository

```bash
git clone https://github.com/OlesVanHermann/multi-agent.git
cd multi-agent
```

### 2. Setup infrastructure

```bash
cd infrastructure
./setup.sh
```

Cela démarre Redis via Docker.

### 3. Configurer votre projet

Lancer l'Architect (900) qui va configurer le système :

```bash
cd multi-agent
claude
```

Puis dans Claude :
```
Lis prompts/900-architect.md
```

L'Architect va :
1. Te demander le nom et type de projet
2. Lire les exemples dans `examples/`
3. Créer les agents dev (3XX) adaptés à ton projet
4. Créer les inventaires
5. Générer `project-config.md`

### 4. Lancer les agents

```bash
./scripts/start-agents.sh
```

## Structure

```
multi-agent/
├── CLAUDE.md              # Documentation principale
├── README.md              # Ce fichier
│
├── prompts/               # Prompts des agents
│   ├── CONVENTIONS.md     # Convention de numérotation
│   ├── PATHS.md           # Variables de chemins
│   ├── 000-*.md           # Super-Masters
│   ├── 100-*.md           # Masters
│   ├── 200-*.md           # Explorers
│   ├── 400-*.md           # Merge
│   ├── 5XX-*.md           # Testers
│   ├── 600-*.md           # Release
│   └── 900-architect.md   # Point d'entrée
│
├── examples/              # Exemples MCP OnlyOffice
│   ├── prompts/           # Prompts dev spécialisés
│   ├── knowledge/         # Inventaires
│   └── pool-requests/     # Exemples de PR
│
├── templates/             # Templates à copier
│   ├── prompts/           # Template agent dev
│   ├── knowledge/         # Template inventaire
│   └── pool-requests/     # Templates PR
│
├── scripts/               # Scripts d'orchestration
├── core/agent-runner/     # Runners Python
├── infrastructure/        # Docker, setup
│
├── pool-requests/         # Queue de travail
│   ├── pending/           # À traiter
│   ├── assigned/          # En cours
│   ├── done/              # Terminés
│   ├── specs/             # Spécifications
│   ├── tests/             # Manifests tests
│   └── knowledge/         # Inventaires
│
├── project/               # Votre code ici
├── sessions/              # Sessions agents
└── logs/                  # Logs
```

## Agents

| ID | Type | Rôle |
|----|------|------|
| 000 | Super-Master | Coordination multi-projets |
| 100 | Master | Coordination projet, dispatch |
| 200 | Explorer | Analyse API, création SPEC |
| 201 | Doc Generator | Sync documentation |
| 3XX | Developer | Implémentation code |
| 400 | Merge | Fusion Git (cherry-pick) |
| 500 | Test | Validation dev → main |
| 501 | Test Creator | Création scripts de test |
| 600 | Release | Publication GitHub |
| **900** | **Architect** | **Configuration système** |

## Commandes utiles

```bash
# Démarrer l'infrastructure
cd infrastructure
./multi-agent.sh start standalone

# Lancer un agent
./multi-agent.sh agent --role master
./multi-agent.sh agent --role slave --id 300

# Communication avec les agents
./multi-agent.sh RW 100 "go"          # Envoyer commande
./multi-agent.sh RO 300               # Observer

# Monitoring
./multi-agent.sh status               # État infrastructure
./multi-agent.sh list                 # Agents connectés
./multi-agent.sh stats                # Statistiques globales
./multi-agent.sh logs 300 100         # Derniers 100 messages

# Scripts pipeline
./scripts/pipeline-status.sh
./scripts/monitor-pipeline.sh
```

Voir [docs/CLI.md](docs/CLI.md) pour la documentation complète du CLI.

## Workflow

```
1. 900 Architect configure le projet
2. 200 Explorer analyse → crée SPEC
3. 100 Master dispatch aux 3XX
4. 300-303 Developers codent en parallèle
5. 400 Merge cherry-pick vers dev
6. 500 Test valide
7. 600 Release publie
```

## Personnalisation

### Ajouter un agent dev

1. Copier `templates/prompts/3XX-developer.md.template`
2. Remplacer les variables (`{AGENT_ID}`, `{DOMAIN_NAME}`, etc.)
3. Sauvegarder dans `prompts/3XX-dev-{domain}.md`
4. Créer l'inventaire correspondant dans `pool-requests/knowledge/`

### Adapter à votre projet

L'Architect (900) s'en charge automatiquement. Il lit les exemples dans `examples/` et crée les prompts adaptés à votre projet.

## Documentation

| Fichier | Description |
|---------|-------------|
| `CLAUDE.md` | Documentation principale du système |
| `docs/CLI.md` | **Référence complète du CLI multi-agent.sh** |
| `infrastructure/INFRASTRUCTURE.md` | Architecture et setup multi-VM |
| `prompts/CONVENTIONS.md` | Convention de numérotation (0XX-9XX) |
| `prompts/PATHS.md` | Variables de chemins ($BASE, $POOL, etc.) |
| `examples/README.md` | Guide des exemples MCP OnlyOffice |

## Contribuer

Les contributions sont les bienvenues !

1. Fork le projet
2. Créer une branche (`git checkout -b feature/amazing-feature`)
3. Commit (`git commit -m 'Add amazing feature'`)
4. Push (`git push origin feature/amazing-feature`)
5. Ouvrir une Pull Request

## Licence

MIT - voir [LICENSE](LICENSE)

## Auteur

**OlesVanHermann**

---

*Multi-Agent System v2.0 - Janvier 2026*
