# Multi-Agent Bridge

Documentation technique du bridge de communication entre Redis Streams et Claude Code.

## Vue d'ensemble

Le bridge remplace l'ancien `agent_runner.py` avec une architecture améliorée :

| Aspect | Ancien (agent_runner) | Nouveau (bridge) |
|--------|----------------------|------------------|
| Exécution Claude | `subprocess.run()` | `pexpect` PTY |
| Communication | Redis Lists | Redis Streams |
| Streaming | Non | Oui (temps réel) |
| Intervention manuelle | Non | Oui |
| Queuing | Basique | Automatique FIFO |
| Sessions Claude | Oui | Oui (préservé) |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     AGENT BRIDGE                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│   │ Redis        │    │ Queue        │    │ Claude       │     │
│   │ Listener     │───>│ Processor    │───>│ PTY          │     │
│   │ (XREAD)      │    │              │    │ (pexpect)    │     │
│   └──────────────┘    └──────────────┘    └──────┬───────┘     │
│                                                   │              │
│   ┌──────────────┐                         ┌─────┴────────┐    │
│   │ Heartbeat    │                         │ Output       │    │
│   │ (10s)        │                         │ Reader       │    │
│   └──────────────┘                         └──────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5 Threads

| Thread | Rôle |
|--------|------|
| `claude_reader` | Lit stdout de Claude en continu |
| `redis_listener` | Écoute inbox via XREAD bloquant |
| `queue_processor` | Exécute les prompts quand IDLE |
| `heartbeat` | Publie status toutes les 10s |
| `main` | Gère stdin (mode interactif) |

### Machine à états

```
IDLE ←─── (timeout 5s sans output) ───→ BUSY
 ↑                                        ↓
 └──────────── (process queue) ──────────┘
```

## Installation

```bash
# Installer les dépendances
pip install -r requirements.txt

# Ou manuellement
pip install redis>=4.0.0 pexpect>=4.8.0
```

## Utilisation

### Mode interactif (un agent)

```bash
python core/agent-bridge/agent.py 300
```

Commandes disponibles :
- `/status` - État actuel (IDLE/BUSY, queue, tasks)
- `/queue` - Taille de la queue
- `/flush` - Vider la queue
- `/session` - Info session Claude
- `/newsession` - Forcer nouvelle session
- `/history` - Derniers 5 échanges
- `/send <id> <msg>` - Envoyer à un autre agent
- `/help` - Aide

### Mode headless (daemon)

```bash
python core/agent-bridge/agent.py 300 --headless
```

### Lancer plusieurs agents

```bash
# Agents spécifiques
./scripts/agent.sh start 300 310

# Tous les agents configurés
./scripts/agent.sh start all

# Arrêter
./scripts/agent.sh stop all
```

## Communication Redis

### Structure des clés

```
ma:agent:{id}          # Hash - métadonnées agent
ma:agent:{id}:inbox    # Stream - messages entrants
ma:agent:{id}:outbox   # Stream - réponses sortantes
```

### Format des messages

**Inbox (requête):**
```json
{
    "prompt": "Analyse ce fichier",
    "from_agent": "100",
    "timestamp": "1706547600",
    "type": "prompt"
}
```

**Outbox (réponse):**
```json
{
    "response": "Voici mon analyse...",
    "from_agent": "300",
    "to_agent": "100",
    "in_reply_to": "1706547600-0",
    "timestamp": "1706547610",
    "chars": "1234"
}
```

### Envoyer un message

```bash
# Via script
./scripts/send.sh 300 "Analyse le README.md"

# Via Redis directement
redis-cli XADD "ma:agent:300:inbox" '*' \
    prompt "Analyse le README.md" \
    from_agent "cli" \
    timestamp "$(date +%s)"
```

### Lire les réponses

```bash
# Temps réel
./scripts/watch.sh 300

# Historique
./scripts/watch.sh 300
```

## Sessions Claude

Le bridge préserve le système de sessions pour le prompt caching :

1. **Première tâche** : `claude --session-id {uuid}` + prompt système complet
2. **Tâches suivantes** : `claude --resume {uuid}` + prompt minimal
3. **Reset** : Nouvelle session après 50 tâches (configurable)

### Économie de tokens

- ~90% d'économie grâce au prompt caching
- Le prompt système n'est envoyé qu'une fois par session

## Monitoring

### Healthcheck

```bash
# Status unique
python core/agent-bridge/healthcheck.py

# Mode watch (refresh 2s)
python core/agent-bridge/healthcheck.py --watch

# Avec stats streams
python core/agent-bridge/healthcheck.py --streams
```

### Monitor temps réel

```bash
./python3 scripts/monitor.py
```

## Orchestration

### Workflows prédéfinis

```bash
# Séquentiel: Explorer → Developer → Tester
python core/agent-bridge/orchestrator.py seq

# Parallèle: plusieurs workers
python core/agent-bridge/orchestrator.py par

# Code review: Developer → Reviewer → Developer
python core/agent-bridge/orchestrator.py review

# Pipeline complet
python core/agent-bridge/orchestrator.py pipeline
```

### API Python

```python
from core.agent_bridge.orchestrator import send_and_wait, broadcast, collect_responses

# Envoyer et attendre réponse
response = send_and_wait(300, "Analyse ce fichier", from_agent=100, timeout=120)

# Broadcast à plusieurs agents
broadcast([300, 301, 302], "Commencez l'analyse")

# Collecter les réponses
responses = collect_responses([300, 301, 302], timeout=60)
```

## Configuration

### Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `REDIS_HOST` | localhost | Hôte Redis |
| `REDIS_PORT` | 6379 | Port Redis |
| `LOG_DIR` | ./logs | Dossier des logs |

### Constantes (dans agent.py)

| Constante | Défaut | Description |
|-----------|--------|-------------|
| `RESPONSE_TIMEOUT` | 5 | Secondes sans output = réponse finie |
| `HEARTBEAT_INTERVAL` | 10 | Intervalle heartbeat (secondes) |
| `MAX_HISTORY` | 50 | Échanges gardés en mémoire |
| `SESSION_TASK_LIMIT` | 50 | Reset session après N tâches |

## Migration depuis agent_runner

### Différences de clés Redis

| Ancien | Nouveau |
|--------|---------|
| `ma:inject:{id}` | `ma:agent:{id}:inbox` |
| `ma:processing:{id}` | (géré par state machine) |
| `ma:agents` (hash global) | `ma:agent:{id}` (hash par agent) |

### Cohabitation

Les deux systèmes peuvent cohabiter :
- Agents `agent_runner.py` utilisent les anciennes clés
- Agents `agent.py` (bridge) utilisent les nouvelles clés

Pour migrer progressivement :
1. Démarrer nouveaux agents avec le bridge
2. Tester le fonctionnement
3. Migrer les anciens agents un par un

## Limitations connues

| Limitation | Impact | Contournement |
|-----------|--------|---------------|
| Timeout fixe 5s | Faux positif si Claude pause | Augmenter `RESPONSE_TIMEOUT` |
| Un prompt à la fois | Pas de batching | Utiliser plusieurs agents |
| Pas d'annulation | Impossible de stopper un prompt | Redémarrer l'agent |

## Troubleshooting

### Agent ne répond pas

1. Vérifier Redis : `redis-cli ping`
2. Vérifier le process : `tmux ls | grep agent-`
3. Vérifier les logs : `tail -F logs/{id}/bridge.log`
4. Vérifier le status : `./python3 scripts/monitor.py`

### Messages perdus

Les messages ne sont jamais perdus grâce aux Redis Streams :
```bash
# Voir tous les messages de l'inbox
redis-cli XRANGE "ma:agent:300:inbox" - +
```

### Session corrompue

Forcer une nouvelle session :
```bash
# En mode interactif
/newsession

# Ou redémarrer l'agent
./scripts/agent.sh stop 300
./scripts/agent.sh start 300
```

---

*Multi-Agent Bridge v1.0 - Janvier 2026*
