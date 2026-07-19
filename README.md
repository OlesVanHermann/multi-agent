# Multi-Agent System v3.1.16

La ligne 3.1 ajoute OpenAI Codex CLI en mode interactif, avec authentification
ChatGPT (forfait, sans API) et trois modèles : `gpt-5.6-sol`,
`gpt-5.6-terra` et `gpt-5.6-luna`. Le moteur est déduit du modèle : choisir un
modèle `gpt-*` utilise Codex, choisir un modèle `claude-*` utilise Claude Code.
Les prompts, fichiers mémoire, historique et canaux Redis restent ceux de
l'agent, quel que soit le moteur.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude](https://img.shields.io/badge/Powered%20by-Claude-blueviolet)](https://claude.ai)

Système d'orchestration multi-agents pour projets de développement complexes avec Claude Code.

> ## ⚠ Exigence d'isolation
>
> Les agents tournent en mode **bypass-permissions** (`--dangerously-skip-permissions`) : chaque agent exécute des commandes shell **sans confirmation humaine**.
>
> - Déployer **uniquement** sur une machine ou un compte Unix **dédié**, sans données sensibles ni accès production. Pas d'usage multi-tenant non maîtrisé.
> - Les profils `login/claude*/settings.json` embarquent des règles `permissions.deny` (lecture/écriture de `setup/secrets.cfg`, écriture de `login/`) — défense en profondeur, **pas** un bac à sable.
> - Pour un confinement OS par agent (utilisateur dédié, conteneur, firejail…), définir `CLAUDE_WRAPPER` avant `./scripts/agent.sh start` ; le préfixe est appliqué à la commande `claude` (ex. `CLAUDE_WRAPPER="sudo -u agent-worker"`).
> - Protéger les secrets : `chmod 600 setup/secrets.cfg` (appliqué par `infra.sh` au démarrage).

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
│  000 ARCHITECT      - Configure le système                      │
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

### 3. Vérifier le moteur CLI

```bash
# Tester que Claude fonctionne
claude --version
echo "test" | claude --print -
```

Le moteur par défaut est Claude Code. Le framework sait aussi piloter Codex
CLI — voir [docs/ENGINES.md](docs/ENGINES.md) pour l’inférence depuis le modèle
et l’usage des modèles GPT-5.6 avec le forfait ChatGPT.

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

# 1. Simuler (optionnel, aucune modification)
./patch/upgrade.sh --dry-run

# 2. Appliquer la mise à jour
./patch/upgrade.sh
```

Le script :
- Met à jour **uniquement** les fichiers framework (`scripts/`, `web/`, `docs/`, `patch/`, `setup/`, `templates/`, `examples/`, `framework/`, `tests/`)
- **Préserve** vos fichiers projet (`prompts/`, `pool-requests/`, `project/`, `sessions/`, `logs/`, `setup/secrets.cfg`)

Voir [patch/HOW_TO_UPGRADE.md](patch/HOW_TO_UPGRADE.md) pour le guide complet.

## Configuration

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `CLAUDE_CONFIG_DIR` | Dossier config Claude | `~/.claude` |
| `CODEX_HOME` | Dossier config Codex (moteur `codex`) | `~/.codex` |
| `AGENT_CLI` | Moteur du bridge (`claude`\|`codex`) — posé par agent.sh | `claude` |
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
./scripts/web.sh start           # Build frontend (si besoin) + uvicorn :8050
./scripts/web.sh stop            # Arrêter uvicorn
./scripts/web.sh rebuild         # Stop + force rebuild frontend + start

# ── Communication ──
./scripts/send.sh 300 "message"  # Envoyer un message à un agent
./scripts/watch.sh 300           # Voir les réponses en temps réel

# ── Proxy (optionnel) ──
./scripts/proxy.sh start         # Reverse proxy 0.0.0.0:80 → 127.0.0.1:8050
./scripts/proxy.sh stop          # Arrêter le proxy

# ── Monitoring ──
python3 scripts/agent-bridge/healthcheck.py   # Healthcheck tous les agents

# ── Hub (framework dev) ──
./patch/hub-receive.sh                     # Lister les patches par projet
./patch/hub-cherry-pick.sh <branch>        # Cherry-pick une branche patch
./patch/hub-release.sh [patch|minor|major] # Test + tag + push GitHub
```

### Commandes interactives (mode non-headless)

```
/status      - État actuel
/queue       - Taille de la queue
/send <id> <msg> - Envoyer à un autre agent
/help        - Aide
```

## Structure du projet

```
multi-agent/
├── scripts/agent-bridge/    # Bridge Redis Streams + Claude (tmux)
│   ├── agent.py             # Agent principal
│   ├── orchestrator.py      # Workflows multi-agents (workflows/*.yaml)
│   └── healthcheck.py       # Monitoring
│
├── scripts/
│   ├── infra.sh             # start/stop infrastructure + Agent 000
│   ├── agent.sh             # start/stop agents workers
│   ├── web.sh               # start/stop/rebuild dashboard
│   ├── proxy.sh             # reverse proxy :80 → :8050
│   ├── send.sh              # Envoyer message à un agent
│   ├── watch.sh             # Voir réponses en temps réel
│   └── status.sh            # Diagnostic rapide du système
│
├── web/                     # Dashboard (FastAPI :8050 + React)
├── framework/               # Outils Chrome/CDP
├── patch/                   # Pipeline de patches + upgrade.sh
├── setup/                   # Installation (Redis, Keycloak, profils)
├── prompts/                 # Prompts système des agents
├── examples/                # Exemples de configuration
├── templates/               # Templates réutilisables
├── docs/                    # Documentation détaillée
├── tests/                   # Tests unitaires et E2E du framework
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
| [docs/ENGINES.md](docs/ENGINES.md) | **Moteurs CLI** — sélection transparente par modèle, profils ChatGPT |
| [patch/HOW_TO_UPGRADE.md](patch/HOW_TO_UPGRADE.md) | Guide de mise à jour |
| [patch/HOW_TO_PATCH.md](patch/HOW_TO_PATCH.md) | **Pipeline de patches** (projet → Hub → GitHub) |
| [docs/AUTH.md](docs/AUTH.md) | Authentification (Keycloak, JWT, WebSocket) |
| [docs/BRIDGE.md](docs/BRIDGE.md) | Documentation technique du bridge |
| [docs/AGENT_MONO.md](docs/AGENT_MONO.md) | Format agent mono |
| [prompts/CONVENTIONS.md](prompts/CONVENTIONS.md) | Convention de numérotation |

## Workflows

### Séquentiel

```bash
python3 scripts/agent-bridge/orchestrator.py seq
```

Explorer → Developer → Tester

### Parallèle

```bash
python3 scripts/agent-bridge/orchestrator.py par
```

Plusieurs workers simultanément

### Code Review

```bash
python3 scripts/agent-bridge/orchestrator.py review
```

Developer → Reviewer → Developer (amélioration)

## Troubleshooting

### Agent ne répond pas

```bash
# Vérifier Redis
redis-cli ping

# Vérifier les sessions tmux
tmux ls | grep agent

# Vérifier les logs (un fichier horodaté par démarrage)
tail -f logs/300/bridge_*.log
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

*Multi-Agent System v3.1.16 - 2026*
