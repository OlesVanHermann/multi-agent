#!/bin/bash
# capture-markers.sh — Relève / revalide les chaînes d'UI d'un moteur CLI.
#
# Les marqueurs de markers.<cli>.yaml ne sont pas devinables : ce sont les
# libellés effectivement rendus par le TUI. Ce script ouvre une session tmux
# jetable, laisse l'opérateur mettre le CLI dans chaque état, et dumpe le pane
# à chaque étape pour que les chaînes soient RELEVÉES, pas inventées.
#
# ÉTAT ACTUEL : claude et codex sont tous deux renseignés.
#   - claude : relevé sur session réelle
#   - codex  : relevé sur le source open source (github.com/openai/codex),
#              code de rendu + snapshots de test — chaque valeur est citée dans
#              markers.codex.yaml
#
# Ce script sert donc désormais à :
#   1. REVALIDER après une mise à jour majeure d'un CLI (les libellés bougent)
#   2. RENSEIGNER un nouveau moteur ajouté à ENGINES
#
# Usage: ./scripts/agent-bridge/capture-markers.sh codex [login_profile]

set -e

CLI="${1:-}"
LOGIN="${2:-}"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$BASE_DIR/logs/markers-capture"

if [ -z "$CLI" ]; then
    echo "Usage: $0 <claude|codex> [login_profile]"
    exit 1
fi

source "$BASE_DIR/scripts/engines.sh"
engine_is_valid "$CLI" || { echo "Moteur inconnu: $CLI"; exit 1; }

command -v "$CLI" >/dev/null || { echo "Binaire '$CLI' introuvable dans le PATH"; exit 1; }

SESSION="markers-capture-$CLI-$$"
mkdir -p "$OUT_DIR"

CMD=$(engine_launch_cmd "$CLI" "$BASE_DIR/login" "$LOGIN" "" "") \
    || { echo "engine_launch_cmd a échoué"; exit 1; }

echo "→ session tmux : $SESSION"
echo "→ commande     : $CMD"
tmux new-session -d -s "$SESSION" -x 110 -y 54
tmux send-keys -t "$SESSION" "cd '$BASE_DIR' && $CMD" Enter

dump() {
    local label="$1"
    local f="$OUT_DIR/${CLI}-${label}.txt"
    tmux capture-pane -t "$SESSION:0.0" -p -J -S -60 > "$f"
    echo "   ✓ $f"
    echo "   ── 6 dernières lignes ──"
    tail -6 "$f" | sed 's/^/   | /'
    echo
}

steps=(
    "idle:Attendre que le CLI soit prêt (composer affiché), puis Entrée ici."
    "busy:Envoyer une tâche longue DANS LE PANE, puis Entrée ici pendant qu'il travaille."
    "done:Attendre la fin de la réponse, puis Entrée ici."
    "select:Provoquer un menu de sélection (ex. /model), puis Entrée ici."
    "compact:Déclencher une compaction de contexte si le CLI l'expose, puis Entrée ici."
)

for step in "${steps[@]}"; do
    label="${step%%:*}"
    hint="${step#*:}"
    echo "── [$label] $hint"
    echo "   (attacher dans un autre terminal : tmux attach -t $SESSION)"
    read -r _
    dump "$label"
done

tmux kill-session -t "$SESSION" 2>/dev/null || true

cat <<EOF

═══════════════════════════════════════════════════════════════════
Dumps écrits dans : $OUT_DIR

Renseigner maintenant scripts/agent-bridge/markers.$CLI.yaml en
recopiant les chaînes EXACTES relevées ci-dessus :

  status_line          → la ligne toujours présente (idle ET busy)
  busy_markers         → ce qui n'apparaît QUE dans le dump [busy]
  prompt_markers       → le caractère du composer dans [idle]
  waiting_select       → la ligne d'invite du dump [select]
  compaction.*         → les libellés du dump [compact]
  context_pct_patterns → le motif de « contexte restant » (regex)

Tant qu'un __A_RENSEIGNER__ subsiste, engines.py refuse de démarrer
le moteur (fail-fast volontaire — voir engines.py).
═══════════════════════════════════════════════════════════════════
EOF
