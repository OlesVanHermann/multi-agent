# Multi-Agent System v2.1

Système d'orchestration multi-agents pour projets de développement complexes.

---

## Vue d'ensemble

Ce système permet de faire tourner jusqu'à **1000 agents** en parallèle avec :

- **Pipeline structurée** : agents spécialisés avec rôles définis
- **Isolation Git** : chaque dev travaille dans son propre clone/branche
- **Communication Redis Streams** : coordination temps réel avec historique
- **Sessions Claude** : prompt caching pour ~90% d'économie de tokens
- **Hiérarchie claire** : Architect → Super-Master → Master → Workers

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    HIÉRARCHIE DES AGENTS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  9XX ARCHITECTS ─────────────────────────────────────────────── │
│  │ Créent la structure, les prompts, configurent le projet      │
│  │ SEULS à pouvoir modifier les prompts                         │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  0XX SUPER-MASTERS ──────────────────────────────────────────── │
│  │ Coordination multi-projets, vision globale                   │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  1XX MASTERS ────────────────────────────────────────────────── │
│  │ Coordination d'un projet, dispatch aux workers               │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         ▼                    ▼                    ▼             │
│  2XX EXPLORERS      3XX DEVELOPERS       4XX INTEGRATORS        │
│  │ Analyse          │ Code               │ Merge Git            │
│  │ Création SPEC    │ Implémentation     │ Synchronisation      │
│  └──────────────────┴────────────────────┴────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  5XX TESTERS ────────────────────────────────────────────────── │
│  │ Tests unitaires, intégration, QA                             │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  6XX RELEASERS ──────────────────────────────────────────────── │
│  │ Release, déploiement, publication                            │
│  └────────────────────────────────────────────────────────────  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Déployer sur une nouvelle machine

```bash
# Copier le dossier multi-agent/
scp -r multi-agent/ user@machine:/chemin/

# Se connecter
ssh user@machine
cd /chemin/multi-agent
```

### 2. Setup infrastructure

```bash
cd infrastructure
./setup.sh
# Démarre Redis via Docker
```

### 3. Lancer l'Architect (900)

```bash
claude --prompt prompts/900-architect.md
```

L'Architect va :
1. Te demander quel projet configurer
2. Lire les exemples dans `examples/`
3. Créer les prompts dev (3XX) adaptés
4. Créer les inventaires
5. Générer `project-config.md`

### 4. Lancer les agents

```bash
./scripts/start-agents.sh
```

---

## Structure

```
multi-agent/
├── CLAUDE.md                    # CE FICHIER
├── README.md                    # Guide de déploiement
├── project-config.md            # Configuration (créé par 900)
│
├── prompts/                     # Prompts des agents
│   ├── CONVENTIONS.md           # Conventions de numérotation
│   ├── PATHS.md                 # Variables de chemins
│   ├── 000-*.md                 # Super-Masters
│   ├── 100-*.md                 # Masters
│   ├── 200-*.md                 # Explorers
│   ├── 3XX-*.md                 # Developers (créés par 900)
│   ├── 400-*.md                 # Integrators
│   ├── 5XX-*.md                 # Testers
│   ├── 600-*.md                 # Releasers
│   └── 900-*.md                 # Architects
│
├── examples/                    # Exemples MCP OnlyOffice
│   ├── prompts/                 # Prompts dev spécialisés
│   ├── knowledge/               # INVENTORY exemples
│   └── pool-requests/           # PR exemples
│
├── templates/                   # Templates vides
│   ├── prompts/
│   ├── knowledge/
│   └── pool-requests/
│
├── scripts/                     # Scripts d'orchestration
│   └── bridge/                  # Scripts pour le nouveau bridge
│
├── core/
│   ├── agent-runner/            # Legacy Python runner
│   ├── agent-bridge/            # NOUVEAU: Bridge PTY + Redis Streams
│   ├── bridge/                  # SSH tunnel Mac↔VM
│   └── dashboard/               # Web dashboard
│
├── docs/                        # Documentation
│   └── BRIDGE.md                # Doc technique du bridge
│
├── infrastructure/              # Docker, setup
│
├── pool-requests/               # Queue de travail
│   ├── pending/                 # À traiter
│   ├── assigned/                # En cours
│   ├── done/                    # Terminés
│   ├── specs/                   # Spécifications
│   ├── tests/                   # Manifests tests
│   ├── knowledge/               # Inventaires
│   └── state/                   # État
│
├── sessions/                    # Sessions agents
├── logs/                        # Logs
└── project/                     # VOTRE PROJET ICI
```

---

## Convention de numérotation

| Plage | Type | Modifie prompts |
|-------|------|-----------------|
| 000-099 | Super-Masters | Non |
| 100-199 | Masters | Non |
| 200-299 | Explorers | Non |
| 300-399 | Developers | Non |
| 400-499 | Integrators | Non |
| 500-599 | Testers | Non |
| 600-699 | Releasers | Non |
| 700-799 | Documenters | Non |
| 800-899 | Monitors | Non |
| **900-999** | **Architects** | **OUI** |

**Règle fondamentale :** Seuls les agents 9XX peuvent modifier les prompts.

---

## Pipeline

```
900 Architect (configure)
         │
         ▼
200 Explorer (analyse) → crée SPEC
         │
         ▼
100 Master (dispatch)
         │
    ┌────┼────┬────┐
    ▼    ▼    ▼    ▼
  300  301  302  303  (Developers - parallèle)
    │    │    │    │
    └────┴────┴────┘
         │
         ▼
400 Merge (cherry-pick)
         │
         ▼
500 Test (validation)
         │
         ▼
600 Release (publication)
```

---

## Communication

### Deux modes disponibles

#### Mode Legacy (agent_runner.py)
```bash
# Redis Lists
redis-cli RPUSH "ma:inject:{AGENT_ID}" "message"
redis-cli RPUSH "ma:inject:300" "go"
```

#### Mode Bridge (agent.py) - RECOMMANDÉ
```bash
# Redis Streams (plus robuste)
./scripts/bridge/send.sh 300 "Analyse le README"

# Ou directement
redis-cli XADD "ma:agent:300:inbox" '*' prompt "message" from_agent "cli" timestamp "$(date +%s)"
```

Voir `docs/BRIDGE.md` pour la documentation complète du bridge.

### Pool Requests (Git)

```
pending/  →  assigned/  →  done/
   │            │            │
 créé        traité      terminé
```

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `prompts/900-architect.md` | Point d'entrée, configure tout |
| `prompts/PATHS.md` | Variables de chemins |
| `project-config.md` | Configuration du projet |
| `pool-requests/knowledge/*.md` | Inventaires (tracking ❌/✅) |
| `examples/` | Exemples à suivre |

---

## Instructions Claude

### Règle critique

**Si tu lis un fichier `prompts/XXX-*.md`, tu DEVIENS cet agent et tu EXÉCUTES IMMÉDIATEMENT sa section DÉMARRAGE.**

- NE JAMAIS demander "Que veux-tu faire ?"
- NE JAMAIS résumer le contenu du prompt
- EXÉCUTER directement les instructions

### Workflow

1. Lire `CLAUDE.md` (ce fichier) pour le contexte
2. Si prompt agent lu → DEVENIR l'agent
3. Exécuter sans confirmation supplémentaire

---

*Multi-Agent System v2.1 - Janvier 2026*
