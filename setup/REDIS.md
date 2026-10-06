# Redis — Setup Multi-Agent

## Vue d'ensemble

Redis est utilisé pour la communication inter-agents via **Redis Streams**.
Il tourne en container Docker local, accessible uniquement en localhost.

---

## Démarrage (recommandé)

```bash
./scripts/infra.sh start
```

Ce script démarre `ma-redis` automatiquement si absent.

---

## Démarrage manuel

```bash
docker run -d --name ma-redis \
    -p 127.0.0.1:6379:6379 \
    -v ma-redis-data:/data \
    --restart unless-stopped \
    redis:7-alpine redis-server --appendonly yes
```

```bash
# Vérifier
redis-cli ping   # → PONG
```

---

## Paramètres

| Paramètre | Valeur |
|-----------|--------|
| Image | `redis:7-alpine` |
| Container | `ma-redis` |
| Port | `127.0.0.1:6379` (localhost uniquement) |
| Volume | `ma-redis-data` |
| Persistance | `appendonly yes` (AOF) |
| Password | Aucun (localhost only) |
| Restart | `unless-stopped` |

---

## Structure des clés

Les adresses sont canoniques et indépendantes de l'installation.

| Clé | Type | Description |
|-----|------|-------------|
| `agent:{id}:inbox` | Stream | Messages entrants d'un agent |
| `agent:{id}` | Hash | Statut heartbeat (IDLE/WORKING/BLOCKED) |
| `agent:{id}:outbox` | Stream | Réponses d'un agent |

Une instance multi-agent utilise son propre Redis ; aucun préfixe variable ne
doit être ajouté aux clés.

---

## Commandes utiles

```bash
# Ping
redis-cli ping

# Voir tous les streams d'agents
redis-cli --scan --pattern 'agent:*:inbox'

# Lire les messages d'un agent
redis-cli XRANGE agent:300:inbox - +

# Envoyer un message manuellement
redis-cli XADD agent:300:inbox '*' prompt "go" from_agent "cli" timestamp "$(date +%s)"

# Voir le statut de tous les agents
redis-cli --scan --pattern 'agent:*' | xargs -I{} redis-cli HGETALL {}

# Flusher (ATTENTION : efface tout)
redis-cli FLUSHALL
```

---

## Gestion du container

```bash
# Démarrer
docker start ma-redis

# Arrêter
docker stop ma-redis

# Logs
docker logs ma-redis

# Supprimer (conserve le volume)
docker rm ma-redis

# Supprimer le volume (PERD LES DONNÉES)
docker volume rm ma-redis-data
```

---

## Troubleshooting

| Symptôme | Vérification |
|----------|-------------|
| `redis-cli ping` échoue | `docker ps \| grep ma-redis` — container tourne ? |
| Port 6379 déjà occupé | `sudo ss -tlnp \| grep 6379` — autre Redis actif ? |
| Container absent de `docker ps` | `docker ps -a \| grep ma-redis` — stoppé ? → `docker start ma-redis` |
| Données perdues au restart | Normal si `FLUSHALL` lancé par `infra.sh start` (flush au démarrage frais) |

---

## Valeurs de référence

| Paramètre | Valeur |
|-----------|--------|
| Image | `redis:7-alpine` |
| Port | `127.0.0.1:6379` |
| Container | `ma-redis` |
| Volume | `ma-redis-data` |
| Auth | Aucune (localhost only) |
| Flush au start | Oui (via `infra.sh start`) |
