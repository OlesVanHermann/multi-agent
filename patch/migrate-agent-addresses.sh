#!/bin/bash
# Migre une installation préfixée vers agent:* / agent-*.
# Usage: ./patch/migrate-agent-addresses.sh [--apply]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$BASE_DIR/scripts/redis.sh"

APPLY=false
[ "${1:-}" = "--apply" ] && APPLY=true

map_key() {
    case "$1" in
        *:agent:*) printf '%s\n' "${1#*:}" ;;
        *:inject:*) printf '%s\n' "${1#*:}" ;;
        *:completion) printf '%s\n' completion ;;
        *:wal) printf '%s\n' wal ;;
        *) return 1 ;;
    esac
}

echo "Migration Redis vers les adresses agent sans préfixe"
echo "Mode: $([ "$APPLY" = true ] && echo APPLY || echo DRY-RUN)"

while IFS= read -r old; do
    [ -n "$old" ] || continue
    new=$(map_key "$old") || continue
    if [ "$($REDIS_CLI EXISTS "$new" 2>/dev/null)" != "0" ]; then
        echo "SKIP collision: $old -> $new"
        continue
    fi
    echo "MOVE $old -> $new"
    [ "$APPLY" = true ] && $REDIS_CLI RENAMENX "$old" "$new" >/dev/null
done < <(
    { $REDIS_CLI --scan --pattern '*:agent:*';
      $REDIS_CLI --scan --pattern '*:inject:*';
      $REDIS_CLI --scan --pattern '*:completion';
      $REDIS_CLI --scan --pattern '*:wal'; } 2>/dev/null | sort -u
)

if [ "$APPLY" = false ]; then
    echo "Aucune modification. Arrêter les agents puis relancer avec --apply."
else
    echo "Redis migré. Redémarrer sous agent-<ID>."
fi
