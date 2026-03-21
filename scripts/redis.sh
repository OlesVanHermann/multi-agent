#!/bin/bash
# redis.sh — Wrapper for redis-cli with auto-auth from scripts/secrets.cfg
# Usage: source this file then use $REDIS_CLI instead of redis-cli
#        or run directly: ./scripts/redis.sh PING
#                         ./scripts/redis.sh XADD A:agent:300:inbox '*' prompt "go"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load password if not already set
if [ -z "${REDIS_PASSWORD:-}" ] && [ -f "$SCRIPT_DIR/secrets.cfg" ]; then
    REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' "$SCRIPT_DIR/secrets.cfg" 2>/dev/null | cut -d= -f2)
fi

# Build redis-cli command with auth (fallback to docker exec if not installed)
if command -v redis-cli &>/dev/null; then
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        REDIS_CLI="redis-cli --no-auth-warning -a $REDIS_PASSWORD"
    else
        REDIS_CLI="redis-cli"
    fi
else
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        REDIS_CLI="docker exec ma-redis redis-cli --no-auth-warning -a $REDIS_PASSWORD"
    else
        REDIS_CLI="docker exec ma-redis redis-cli"
    fi
fi
export REDIS_CLI

# If called directly (not sourced), execute the command
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    exec $REDIS_CLI "$@"
fi
