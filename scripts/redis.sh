#!/bin/bash
# redis.sh — Wrapper for redis-cli with auto-auth from scripts/secrets.cfg
# Usage: source this file then use $REDIS_CLI instead of redis-cli
#        or run directly: ./scripts/redis.sh PING
#                         ./scripts/redis.sh XADD agent:NNN:inbox '*' prompt "go"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Charge uniquement les variables réellement absentes. Une valeur explicitement
# vide (notamment REDIS_PASSWORD='') est une configuration volontaire : elle ne
# doit jamais réactiver silencieusement le secret de setup/secrets.cfg.
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRETS_FILE="$BASE_DIR/setup/secrets.cfg"
redis_config_value() {
    local name="$1"
    [ -f "$SECRETS_FILE" ] || return 0
    grep -m1 "^${name}=" "$SECRETS_FILE" 2>/dev/null | cut -d= -f2-
}
if [ -z "${REDIS_HOST+x}" ]; then
    REDIS_HOST=$(redis_config_value REDIS_HOST)
fi
if [ -z "${REDIS_PORT+x}" ]; then
    REDIS_PORT=$(redis_config_value REDIS_PORT)
fi
if [ -z "${REDIS_DB+x}" ]; then
    REDIS_DB=$(redis_config_value REDIS_DB)
fi
if [ -z "${REDIS_PASSWORD+x}" ]; then
    REDIS_PASSWORD=$(redis_config_value REDIS_PASSWORD)
fi
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DB="${REDIS_DB:-0}"

case "$REDIS_HOST" in
    *[!A-Za-z0-9_.:-]*)
        echo "[redis.sh] ERROR: invalid REDIS_HOST" >&2
        export REDIS_CLI_VALID=false
        return 1 2>/dev/null || exit 1
        ;;
esac
case "$REDIS_PORT:$REDIS_DB" in
    *[!0-9:]*|:*|*:)
        echo "[redis.sh] ERROR: REDIS_PORT and REDIS_DB must be numeric" >&2
        export REDIS_CLI_VALID=false
        return 1 2>/dev/null || exit 1
        ;;
esac
export REDIS_HOST REDIS_PORT REDIS_DB REDIS_PASSWORD

# Export password via env var (invisible to ps aux, unlike -a flag)
if [ -n "${REDIS_PASSWORD:-}" ]; then
    export REDISCLI_AUTH="$REDIS_PASSWORD"
else
    unset REDISCLI_AUTH
fi

# Build redis-cli command (fallback to docker exec if not installed)
# NB : $REDIS_CLI est expansé SANS quotes par les consommateurs (word splitting).
# Seuls host/port/db, validés ci-dessus et non secrets, sont incrustés. Le mot
# de passe passe uniquement par l'env exporté REDISCLI_AUTH — `docker exec -e
# VAR` (sans valeur) le propage, et sudo le préserve via --preserve-env.
_docker_redis_cli() {
    if docker info &>/dev/null 2>&1; then
        echo "docker exec -e REDISCLI_AUTH ma-redis redis-cli -n $REDIS_DB"
    else
        echo "sudo --preserve-env=REDISCLI_AUTH docker exec -e REDISCLI_AUTH ma-redis redis-cli -n $REDIS_DB"
    fi
}

_docker_fallback_allowed() {
    # Ne jamais changer silencieusement d'instance quand un endpoint distant
    # ou un port explicite ne repond pas. Le conteneur ma-redis n'est un repli
    # valide que pour l'endpoint local standard qu'il expose.
    case "$REDIS_HOST:$REDIS_PORT" in
        localhost:6379|127.0.0.1:6379|::1:6379) return 0 ;;
        *) return 1 ;;
    esac
}

if command -v redis-cli &>/dev/null; then
    REDIS_CLI="redis-cli -h $REDIS_HOST -p $REDIS_PORT -n $REDIS_DB"
elif _docker_fallback_allowed; then
    REDIS_CLI="$(_docker_redis_cli)"
else
    # Commande volontairement invalide : la validation ci-dessous expose
    # l'indisponibilite sans basculer vers une autre base.
    REDIS_CLI="redis-cli -h $REDIS_HOST -p $REDIS_PORT -n $REDIS_DB"
fi
export REDIS_CLI

# Validate REDIS_CLI works. Le choix du repli Docker a deja ete fait ci-dessus
# uniquement si redis-cli est absent ; un echec de connexion ne change jamais
# l'instance cible.
_redis_validate() {
    $REDIS_CLI PING 2>/dev/null | grep -q PONG
}

if ! _redis_validate; then
    echo "[redis.sh] WARNING: No working Redis CLI found" >&2
    export REDIS_CLI_VALID=false
else
    export REDIS_CLI_VALID=true
fi

# If called directly (not sourced), execute the command
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    exec $REDIS_CLI "$@"
fi
