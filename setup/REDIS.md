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

Les clés sont préfixées par `MA_PREFIX` (défaut : `A`).

| Clé | Type | Description |
|-----|------|-------------|
| `A:agent:{id}:inbox` | Stream | Messages entrants d'un agent |
| `A:agent:{id}:status` | Hash | Statut heartbeat (IDLE/WORKING/BLOCKED) |
| `A:agent:{id}:log` | Stream | Logs de l'agent |

Le préfixe `A` est configurable dans `project-config.md` (`MA_PREFIX=A`).
Permet de faire tourner plusieurs projets sur le même Redis.

---

## Commandes utiles

```bash
# Ping
redis-cli ping

# Voir tous les streams d'agents
redis-cli --scan --pattern 'A:agent:*:inbox'

# Lire les messages d'un agent
redis-cli XRANGE A:agent:300:inbox - +

# Envoyer un message manuellement
redis-cli XADD A:agent:300:inbox '*' prompt "go" from_agent "cli" timestamp "$(date +%s)"

# Voir le statut de tous les agents
redis-cli --scan --pattern 'A:agent:*:status' | xargs -I{} redis-cli HGETALL {}

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
