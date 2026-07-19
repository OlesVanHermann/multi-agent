#!/bin/bash
# redis.sh — Wrapper for redis-cli with auto-auth from scripts/secrets.cfg
# Usage: source this file then use $REDIS_CLI instead of redis-cli
#        or run directly: ./scripts/redis.sh PING
#                         ./scripts/redis.sh XADD agent:NNN:inbox '*' prompt "go"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load password if not already set
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -z "${REDIS_PASSWORD:-}" ] && [ -f "$BASE_DIR/setup/secrets.cfg" ]; then
    REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' "$BASE_DIR/setup/secrets.cfg" 2>/dev/null | cut -d= -f2)
fi

# Export password via env var (invisible to ps aux, unlike -a flag)
if [ -n "${REDIS_PASSWORD:-}" ]; then
    export REDISCLI_AUTH="$REDIS_PASSWORD"
fi

# Build redis-cli command (fallback to docker exec if not installed)
# NB : $REDIS_CLI est expansé SANS quotes par les consommateurs (word splitting).
# Aucune valeur ne doit donc être incrustée dans la chaîne : le mot de passe
# passe uniquement par l'env exporté REDISCLI_AUTH — `docker exec -e VAR`
# (sans valeur) le propage, et sudo le préserve via --preserve-env.
_docker_redis_cli() {
    if docker info &>/dev/null 2>&1; then
        echo "docker exec -e REDISCLI_AUTH ma-redis redis-cli"
    else
        echo "sudo --preserve-env=REDISCLI_AUTH docker exec -e REDISCLI_AUTH ma-redis redis-cli"
    fi
}

if command -v redis-cli &>/dev/null; then
    REDIS_CLI="redis-cli"
else
    REDIS_CLI="$(_docker_redis_cli)"
fi
export REDIS_CLI

# Validate REDIS_CLI works — if not, try docker fallback
_redis_validate() {
    $REDIS_CLI PING 2>/dev/null | grep -q PONG
}

if ! _redis_validate; then
    # Current method failed, try docker fallback
    REDIS_CLI="$(_docker_redis_cli)"
    export REDIS_CLI

    if ! _redis_validate; then
        echo "[redis.sh] WARNING: No working Redis CLI found" >&2
        export REDIS_CLI_VALID=false
    else
        export REDIS_CLI_VALID=true
    fi
else
    export REDIS_CLI_VALID=true
fi

# If called directly (not sourced), execute the command
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    exec $REDIS_CLI "$@"
fi
