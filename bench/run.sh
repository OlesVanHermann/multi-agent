#!/bin/bash
# V3/C0 — Exécute le banc et collecte les métriques.
#
# Usage: bench/run.sh <label> [n_runs] [dev|heldout] [v2|v3]
#
#   label    : étiquette du run (ex: v2.12.22-baseline, v3-core) → results/<label>.jsonl
#   n_runs   : répétitions par tâche (défaut 1 ; baseline plan : >=5 sur held-out)
#   split    : dev | heldout (défaut heldout)
#   mode     : v3 = dispatch avec verify=bench/oracle/<tid>/verify.sh (boucle C1)
#              v2 = dispatch SANS verify_cmd (baseline — le succès est mesuré
#                   post-hoc par le même oracle, jamais montré à l'agent)
#
# Pour chaque tâche : reset du project/ sur l'état de départ figé
# (tag git bench-base-<tid>, posé par l'import — voir annexe §4.3),
# dispatch via l'orchestrator, puis collect.py lit WAL + completion +
# oracle post-hoc et ajoute une ligne JSONL dans results/.
#
# Prérequis : infra démarrée (Redis + bridge de l'agent 300).
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${1:?Usage: bench/run.sh <label> [n_runs] [dev|heldout] [v2|v3]}"
RUNS="${2:-1}"
SPLIT="${3:-heldout}"
MODE="${4:-v3}"
PROJECT="${PROJECT_DIR:-$BASE/project}"

for TID in $("$BASE/bench/list_tasks.sh" "$SPLIT"); do
    TASKFILE=$(find "$BASE/bench/tasks" -mindepth 3 -maxdepth 3 \
               -path "*/$TID/task.md" | head -1)
    if [ -z "$TASKFILE" ]; then
        echo "[bench] SKIP $TID : task.md introuvable" >&2
        continue
    fi

    VERIFY=""
    if [ "$MODE" = "v3" ]; then
        VERIFY="$BASE/bench/oracle/$TID/verify.sh"
        if [ ! -x "$VERIFY" ]; then
            echo "[bench] SKIP $TID : oracle absent ou non exécutable" >&2
            continue
        fi
    fi

    for i in $(seq "$RUNS"); do
        # État de départ figé (les runs doivent être appariés sur la même base)
        if git -C "$PROJECT" rev-parse -q --verify "bench-base-$TID" >/dev/null 2>&1; then
            git -C "$PROJECT" checkout -f "bench-base-$TID"
        else
            echo "[bench] WARN $TID : tag bench-base-$TID absent," \
                 "état de départ non figé" >&2
        fi

        echo "[bench] === $LABEL / $TID / run $i ($MODE) ==="
        T0=$(date +%s)
        python3 "$BASE/scripts/agent-bridge/orchestrator.py" \
            "$BASE/bench/tasks/wf-single.yaml" \
            --var task="$TID" --var taskfile="$TASKFILE" --var verify="$VERIFY" \
            --state "$BASE/bench/results/state-$LABEL-$TID-$i.json" || true
        T1=$(date +%s)

        python3 "$BASE/bench/collect.py" \
            "$LABEL" "$TID" "$i" "$T0" "$T1" "$MODE"
    done
done

python3 "$BASE/bench/aggregate.py" "$LABEL"
