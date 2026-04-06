#!/bin/bash
# redis.sh — Wrapper for redis-cli with auto-auth from scripts/secrets.cfg
# Usage: source this file then use $REDIS_CLI instead of redis-cli
#        or run directly: ./scripts/redis.sh PING
#                         ./scripts/redis.sh XADD A:agent:300:inbox '*' prompt "go"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load password if not already set
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -z "${REDIS_PASSWORD:-}" ] && [ -f "$BASE_DIR/setup/secrets.cfg" ]; then
    REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' "$BASE_DIR/setup/secrets.cfg" 2>/dev/null | cut -d= -f2)
fi

# Build redis-cli command with auth (fallback to docker exec if not installed)
if command -v redis-cli &>/dev/null; then
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        REDIS_CLI="redis-cli --no-auth-warning -a $REDIS_PASSWORD"
    else
        REDIS_CLI="redis-cli"
    fi
else
    # Detect if sudo is needed for docker
    _DOCKER="docker"
    if ! docker info &>/dev/null 2>&1 && sudo docker info &>/dev/null 2>&1; then
        _DOCKER="sudo docker"
    fi
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        REDIS_CLI="$_DOCKER exec ma-redis redis-cli --no-auth-warning -a $REDIS_PASSWORD"
    else
        REDIS_CLI="$_DOCKER exec ma-redis redis-cli"
    fi
fi
export REDIS_CLI

# If called directly (not sourced), execute the command
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    exec $REDIS_CLI "$@"
fi
