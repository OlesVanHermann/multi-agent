# Multi-Agent System v2.1

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude](https://img.shields.io/badge/Powered%20by-Claude-blueviolet)](https://claude.ai)

Système d'orchestration multi-agents pour projets de développement complexes avec Claude Code.

## Caractéristiques

- **Jusqu'à 1000 agents** en parallèle
- **Communication Redis Streams** : coordination temps réel avec historique
- **Sessions Claude** : prompt caching pour ~90% d'économie de tokens
- **Hiérarchie claire** : Architect → Super-Master → Master → Workers
- **Mode headless** : agents en daemon dans tmux
- **Intervention manuelle** : commandes interactives pendant l'exécution

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

## Prérequis

- **Python 3.8+** avec pip
- **Redis** (local ou Docker)
- **Claude Code CLI** installé et authentifié
- **tmux** (pour le mode headless)
- **Git**

## Installation rapide

### 1. Cloner le repository

```bash
git clone https://github.com/OlesVanHermann/multi-agent.git
cd multi-agent
```

### 2. Installer les dépendances

```bash
# Python
pip install -r requirements.txt

# Redis (Ubuntu/Debian)
sudo apt-get install redis-server redis-tools tmux

# Ou via Docker
docker run -d --name redis -p 127.0.0.1:6379:6379 redis:7-alpine
```

### 3. Vérifier Claude Code

```bash
# Tester que Claude fonctionne
claude --version
echo "test" | claude --print -
```

### 4. Lancer les agents

```bash
# Tout lancer (infra + agents)
./scripts/agent.sh start all

# Ou un agent spécifique
./scripts/agent.sh start 300

# Infra seule (Docker, Redis, Keycloak, Dashboard, Agent 000)
./scripts/infra.sh start
```

## Mise à jour (Upgrade)

Si vous avez déjà une installation (ex: v2.0) et voulez mettre à jour :

```bash
cd /chemin/vers/multi-agent

# 1. Télécharger le script de mise à jour
curl -O https://raw.githubusercontent.com/OlesVanHermann/multi-agent/main/upgrade.sh
chmod +x upgrade.sh

# 2. Simuler (optionnel, aucune modification)
./upgrade.sh --dry-run

# 3. Appliquer la mise à jour
./upgrade.sh
```

Le script :
- Met à jour **uniquement** les fichiers framework (`core/`, `scripts/`, `web/`, `docs/`)
- **Préserve** vos fichiers projet (`prompts/`, `pool-requests/`, `project/`, `project-config.md`)

Voir [UPGRADE.md](UPGRADE.md) et [upgrades/](upgrades/) pour les détails par version.

## Configuration

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `CLAUDE_CONFIG_DIR` | Dossier config Claude | `~/.claude` |
| `CLAUDE_CMD` | Commande Claude | `claude` |
| `REDIS_HOST` | Hôte Redis | `localhost` |
| `REDIS_PORT` | Port Redis | `6379` |

### Profils Claude personnalisés

Si vous utilisez plusieurs profils Claude :

```bash
export CLAUDE_CONFIG_DIR=~/.claude-profiles/mon-profil
./scripts/agent.sh start all
```

## Utilisation

### Commandes de base

```bash
# ── Infrastructure ──
./scripts/infra.sh start          # Docker, Redis, Keycloak, Dashboard, Agent 000
./scripts/infra.sh stop           # Tout arrêter (agents + infra)

# ── Agents ──
./scripts/agent.sh start all     # Lancer tous les agents (auto-détecte depuis prompts/)
./scripts/agent.sh start 300     # Lancer un agent spécifique
./scripts/agent.sh stop all      # Arrêter les agents (sauf 000 et 9XX)
./scripts/agent.sh stop 300      # Arrêter un agent

# ── Dashboard web ──
./scripts/web.sh start           # Build frontend (si besoin) + uvicorn :8000
./scripts/web.sh stop            # Arrêter uvicorn
./scripts/web.sh rebuild         # Stop + force rebuild frontend + start

# ── Communication ──
./scripts/send.sh 300 "message"  # Envoyer un message à un agent
./scripts/watch.sh 300           # Voir les réponses en temps réel

# ── Proxy (optionnel) ──
./scripts/proxy.sh start         # Reverse proxy 0.0.0.0:80 → 127.0.0.1:8000
./scripts/proxy.sh stop          # Arrêter le proxy

# ── Monitoring ──
python3 core/agent-bridge/healthcheck.py   # Healthcheck tous les agents

# ── Hub (framework dev) ──
./scripts/hub-receive.sh                   # Lister les patches par projet
./scripts/hub-cherry-pick.sh <branch>      # Cherry-pick une branche patch
./scripts/hub-release.sh [patch|minor|major]  # Test + tag + push GitHub
```

### Commandes interactives (mode non-headless)

```
/status      - État actuel
/queue       - Taille de la queue
/flush       - Vider la queue
/session     - Info session Claude
/send <id> <msg> - Envoyer à un autre agent
/help        - Aide
```

## Structure du projet

```
multi-agent/
├── core/
│   ├── agent-bridge/        # Bridge Redis Streams + Claude
│   │   ├── agent.py         # Agent principal
│   │   ├── orchestrator.py  # Workflows multi-agents
│   │   └── healthcheck.py   # Monitoring
│   ├── bridge/              # SSH tunnel Mac↔VM
│   └── dashboard/           # Web dashboard
│
├── scripts/
│   ├── infra.sh             # start/stop infrastructure + Agent 000
│   ├── agent.sh             # start/stop agents workers
│   ├── web.sh               # start/stop/rebuild dashboard
│   ├── proxy.sh             # reverse proxy :80 → :8000
│   ├── send.sh              # Envoyer message à un agent
│   ├── watch.sh             # Voir réponses en temps réel
│   ├── hub-receive.sh       # Lister patches reçus
│   ├── hub-cherry-pick.sh   # Cherry-pick patches
│   └── hub-release.sh       # Test + tag + push GitHub
│
├── prompts/                 # Prompts système des agents
├── examples/                # Exemples de configuration
├── templates/               # Templates pour nouveaux projets
├── docs/                    # Documentation détaillée
│
├── pool-requests/           # Queue de travail (fichiers)
├── logs/                    # Logs des agents
└── project/                 # Votre code ici
```

## Personnalisation

### Créer un nouveau type d'agent

1. Copier un prompt existant dans `prompts/`
2. Modifier l'ID et les instructions
3. Lancer avec `./scripts/agent.sh start <id>`

### Configurer pour votre projet

1. Placer votre code dans `project/`
2. Modifier les prompts des agents pour votre domaine
3. Créer des inventaires dans `pool-requests/knowledge/`
4. Adapter les chemins dans les prompts (voir `prompts/PATHS.md`)

> **Note** : Les prompts dans `prompts/` contiennent des exemples basés sur un projet OnlyOffice.
> Consultez `examples/` pour voir un cas d'usage concret, puis adaptez les prompts à votre projet.

## Documentation

| Fichier | Description |
|---------|-------------|
| [CLAUDE.md](CLAUDE.md) | Documentation principale |
| [UPGRADE.md](UPGRADE.md) | Guide de mise à jour (processus général) |
| [upgrades/](upgrades/) | **Guides par version** (2.0→2.1, etc.) |
| [docs/BRIDGE.md](docs/BRIDGE.md) | Documentation technique du bridge |
| [docs/CLI.md](docs/CLI.md) | Référence CLI |
| [prompts/CONVENTIONS.md](prompts/CONVENTIONS.md) | Convention de numérotation |

## Workflows

### Séquentiel

```bash
python3 core/agent-bridge/orchestrator.py seq
```

Explorer → Developer → Tester

### Parallèle

```bash
python3 core/agent-bridge/orchestrator.py par
```

Plusieurs workers simultanément

### Code Review

```bash
python3 core/agent-bridge/orchestrator.py review
```

Developer → Reviewer → Developer (amélioration)

## Troubleshooting

### Agent ne répond pas

```bash
# Vérifier Redis
redis-cli ping

# Vérifier les sessions tmux
tmux ls | grep agent

# Vérifier les logs
tail -f logs/300/bridge.log
```

### Erreur "Invalid API key"

```bash
# Vérifier que Claude fonctionne
claude --print "test"

# Si vous utilisez un profil personnalisé
export CLAUDE_CONFIG_DIR=~/.claude-profiles/votre-profil
```

### Redémarrer proprement

```bash
./scripts/infra.sh stop
redis-cli FLUSHDB
./scripts/agent.sh start all
```

## Contribuer

1. Fork le projet
2. Créer une branche (`git checkout -b feature/amazing-feature`)
3. Commit (`git commit -m 'Add amazing feature'`)
4. Push (`git push origin feature/amazing-feature`)
5. Ouvrir une Pull Request

## Licence

MIT - voir [LICENSE](LICENSE)

---

*Multi-Agent System v2.1 - 2026*
