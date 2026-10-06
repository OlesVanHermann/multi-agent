#!/bin/bash
# V3/C0 — Liste les task_ids du banc pour un split donné.
#
# Usage: bench/list_tasks.sh [dev|heldout|all]
#
# Le split held-out est défini par bench/heldout.txt (une ligne = un task_id,
# lignes vides et commentaires # ignorés). dev = toutes les tâches - held-out.
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
SPLIT="${1:-all}"

ALL=$(find "$BASE/bench/tasks" -mindepth 2 -maxdepth 2 -type d 2>/dev/null \
      | xargs -rn1 basename | sort)
HELD=$(grep -vE '^\s*(#|$)' "$BASE/bench/heldout.txt" 2>/dev/null | sort || true)

case "$SPLIT" in
    all)     echo "$ALL" ;;
    heldout) echo "$HELD" ;;
    dev)     comm -23 <(echo "$ALL") <(echo "$HELD") ;;
    *)       echo "Usage: $0 [dev|heldout|all]" >&2; exit 1 ;;
esac
