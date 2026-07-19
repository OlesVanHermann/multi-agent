#!/bin/bash
# scroll-tmux-web.sh — Restaure le scroll tmux dans le dashboard web
#
# A executer SUR la machine cible (ex: mx9), depuis ~/multi-agent :
#   scp patch/scroll-tmux-web.sh mx9:~/multi-agent/patch/
#   ssh mx9 'cd ~/multi-agent && bash patch/scroll-tmux-web.sh'
#
# Idempotent : peut etre relance sans risque.
#
# Cause du bug : claude en "tui: fullscreen" utilise l'ecran alterne (alternate
# screen) -> tmux ne garde aucun scrollback -> le dashboard (qui fait des
# capture-pane) ne voit que l'ecran courant. Le fix = "tui: default" (rendu
# buffer normal) dans les profils login/ (non versionne, d'ou ce script).
#
# "& co" : panes worker 110x54 + history-limit 10000 + capture backend -S 3000.

set -euo pipefail
BASE="${BASE:-$HOME/multi-agent}"
TS=$(date +%Y%m%d_%H%M%S)
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
info() { echo -e "${CYAN}[..]${NC} $1"; }
warn() { echo -e "${YELLOW}[!!]${NC} $1"; }

cd "$BASE"

# ── 1. FIX CENTRAL : tui fullscreen -> default dans tous les profils login ──
info "1/4 login/*/settings.json : tui fullscreen -> default"
changed=0
for f in login/claude*/settings.json; do
    [ -f "$f" ] || continue
    cur=$(python3 -c "import json;print(json.load(open('$f')).get('tui',''))" 2>/dev/null || echo "")
    if [ "$cur" = "fullscreen" ]; then
        cp "$f" "$f.bak-$TS"
        python3 -c "import json;f='$f';d=json.load(open(f));d['tui']='default';json.dump(d,open(f,'w'),indent=2)"
        ok "  $f : fullscreen -> default (backup .bak-$TS)"
        changed=$((changed+1))
    fi
done
[ "$changed" = 0 ] && ok "  deja en default/absent partout (rien a faire)"

# ── 2. agent.sh : panes worker 110x54 + history-limit (futurs demarrages) ──
info "2/4 scripts/agent.sh : taille worker + history-limit"
if [ -f scripts/agent.sh ]; then
    cp scripts/agent.sh "scripts/agent.sh.bak-$TS"
    # hauteur 24 ou 49 -> 54 (sessions worker)
    sed -i -E 's/(tmux new-session -d -s "\$SESSION(_NAME)?" -x "\$\{TMUX_COLS:-[0-9]+\}") -y (24|49)/\1 -y 54/g' scripts/agent.sh
    # largeur par defaut 80 -> 110 (worker)
    sed -i -E 's/(tmux new-session -d -s "\$SESSION(_NAME)?" -x "\$\{TMUX_COLS:)-80\}"/\1-110}"/g' scripts/agent.sh
    if grep -q -- '-y 54' scripts/agent.sh; then ok "  panes worker en 110x54"; else warn "  format agent.sh different, taille non modifiee (verifier a la main)"; fi
    # cas ancienne version : new-session sans -x/-y du tout
    if grep -qE 'tmux new-session -d -s "\$SESSION(_NAME)?"$' scripts/agent.sh; then
        sed -i -E 's/(tmux new-session -d -s "\$SESSION(_NAME)?")$/\1 -x "${TMUX_COLS:-110}" -y 54/g' scripts/agent.sh
        ok "  ajout taille aux new-session worker sans dimension"
    fi
else
    warn "  scripts/agent.sh absent"
fi

# ── 3. backend : profondeur de capture pane 500 -> 3000 (scroll profond) ──
info "3/4 backend : capture pane -S 500 -> 3000"
A="web/backend/multi_agent/routers/agents.py"
W="web/backend/multi_agent/routers/ws.py"
[ -f "$A" ] && sed -i -E 's/(def get_agent_output\(agent_id: str = ValidAgentId, lines: int = )500\)/\13000)/' "$A" && ok "  agents.py /output default -> 3000" || warn "  $A absent"
[ -f "$W" ] && sed -i -E 's/(_capture_agent_pane\(agent_id, )lines=500(, ansi=False\))/\1lines=3000\2/' "$W" && ok "  ws.py WS live -> 3000" || warn "  $W absent"

# ── 4. sessions live : history-limit 10000 (effet immediat, sans restart) ──
info "4/4 sessions tmux live : history-limit 10000"
n=0
for s in $(tmux list-sessions -F "#{session_name}" 2>/dev/null | grep '^agent-'); do
    tmux set-option -t "$s" history-limit 10000 2>/dev/null && n=$((n+1)) || true
done
ok "  history-limit applique a $n sessions live"

echo ""
echo -e "${GREEN}=== Patch applique. ===${NC}"
echo "Pour que tui:default prenne effet, RELANCER les agents :"
echo "    ./scripts/agent.sh restart all        # (ou par agent : restart 300-500)"
echo "Pour la profondeur de capture backend, RELANCER le dashboard :"
echo "    ./scripts/web.sh stop && ./scripts/web.sh start"
echo ""
echo "Verifier ensuite qu'un pane est bien en buffer normal (scrollback) :"
echo "    tmux display-message -p -t agent-NNN-NNN:0 '#{alternate_on}'   # doit afficher 0"
