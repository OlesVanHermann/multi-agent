#!/usr/bin/env python3
"""
debug-color.py — détecte la couleur qu'afficherait le dashboard pour un agent

Réplique exacte de la logique server.py :
  - tmux capture-pane -S -30  (même script bash)
  - Redis hgetall + reload_sent flag
  - _resolve_agent_statuses_batch (même priorité)
  - merge Redis vs tmux override (même règle stopped/CRITICAL)

Usage: python3 scripts/debug-color.py <AGENT_ID>
Exemple: python3 scripts/debug-color.py 334-134
         python3 scripts/debug-color.py 300
"""

import sys
import os
import subprocess

MA_PREFIX = os.environ.get("MA_PREFIX", "A")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")

# AgentGrid.jsx getStatusColor()
COLOR_MAP = {
    "has_bashes":        "VERT          (has_bashes)       — bashes arrière-plan",
    "busy":              "VERT CLAIR    (busy)             — Claude traite un prompt",
    "waiting_approval":  "BLEU          (waiting_approval) — Enter to select",
    "plan_mode":         "BLEU FONCÉ   (plan_mode)        — plan mode on",
    "context_warning":   "ORANGE        (context_warning)  — contexte 1-10%",
    "context_compacted": "ROUGE         (context_compacted)— compaction en cours / ctx 0%",
    "needs_clear":       "ROUGE FONCÉ  (needs_clear)      — /clear auto déclenché",
    "active":            "GRIS          (active)           — Claude idle",
    "idle":              "GRIS          (idle)",
    "stale":             "GRIS          (stale)",
    "starting":          "BLANC         (starting)",
    "stopped":           "GRIS FONCÉ   (stopped)          — Claude process absent",
    "error":             "ROUGE FONCÉ  (error)",
    "blocked":           "ROUGE FONCÉ  (blocked)",
}


def detect_tmux(agent_id):
    """Réplique exacte du script bash inline de server.py."""
    session = f"{MA_PREFIX}-agent-{agent_id}"
    script = f"""
s="{session}"
id="{agent_id}"
out=$(tmux capture-pane -t "$s:0.0" -p -J -S -30 2>/dev/null)
pane_cmd=$(tmux display-message -t "$s:0.0" -p "#{{pane_current_command}}" 2>/dev/null || echo "")
claude_alive=0
if [[ "$pane_cmd" == "claude" || "$pane_cmd" == "node" ]]; then claude_alive=1; fi
busy=0; has_bashes=0; has_down=0; plan_mode=0; compacted=0; ctx=-1
done_compacting=0; prompt_loaded=0; ctx_limit=0; api_error=0; model_change=0; waiting_approval=0
bp_line=$(echo "$out" | grep "bypass permissions" | tail -1)
if echo "$bp_line" | grep -q "bashes"; then has_bashes=1; fi
if [ "$claude_alive" -eq 0 ]; then
    busy=0
elif echo "$bp_line" | grep -q "esc to interrupt"; then
    busy=1  # Claude runs subagents: ❯ visible but "esc to interrupt" = busy
elif echo "$out" | tail -10 | grep -q "❯"; then
    busy=0
else
    busy=1
fi
if echo "$bp_line" | grep -q "↓"; then has_down=1; fi
if echo "$out" | grep -q "plan mode on"; then plan_mode=1; fi
if echo "$out" | grep -q "Enter to select"; then waiting_approval=1; fi
if echo "$out" | grep -qiE "compacting conversation"; then compacted=1; fi
if echo "$out" | grep -qi "Conversation compacted"; then done_compacting=1; fi
if [ "$done_compacting" -eq 1 ] && echo "$out" | grep -qE "prompts/[0-9]+/${{id}}[.-]|prompts/${{id}}-"; then prompt_loaded=1; fi
pct=$(echo "$out" | grep -oE "[0-9]+% until auto-compact|auto-compact: [0-9]+%" | tail -1 | grep -oE "[0-9]+")
if [ -n "$pct" ]; then ctx=$pct; fi
if echo "$out" | grep -q "Context limit reached"; then ctx_limit=1; fi
api_err_count=$(echo "$out" | grep -c "API Error:" 2>/dev/null || echo 0)
if [ "$api_err_count" -ge 3 ]; then api_error=1; fi
if echo "$out" | grep -q "/model "; then model_change=1; fi

printf "===RAW===\\n"
echo "$out" | tail -20
printf "===SIGNALS===\\n"
echo "pane_cmd=$pane_cmd"
echo "claude_alive=$claude_alive"
echo "busy=$busy"
echo "has_bashes=$has_bashes"
echo "has_down=$has_down"
echo "plan_mode=$plan_mode"
echo "waiting_approval=$waiting_approval"
echo "compacted=$compacted"
echo "done_compacting=$done_compacting"
echo "prompt_loaded=$prompt_loaded"
echo "ctx=$ctx"
echo "ctx_limit=$ctx_limit"
echo "api_error=$api_error"
echo "model_change=$model_change"
echo "bp_line=$bp_line"
"""
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout


def parse_output(output):
    raw_lines = []
    signals = {}
    section = None
    for line in output.split("\n"):
        if line == "===RAW===":
            section = "raw"
            continue
        if line == "===SIGNALS===":
            section = "signals"
            continue
        if section == "raw":
            raw_lines.append(line)
        elif section == "signals" and "=" in line:
            k, _, v = line.partition("=")
            signals[k.strip()] = v.strip()
    return raw_lines, signals


def get_redis(agent_id):
    try:
        import redis
        kwargs = {"host": REDIS_HOST, "port": REDIS_PORT, "decode_responses": True}
        if REDIS_PASSWORD:
            kwargs["password"] = REDIS_PASSWORD
        r = redis.Redis(**kwargs)
        data = r.hgetall(f"{MA_PREFIX}:agent:{agent_id}")
        reload_flag = r.get(f"{MA_PREFIX}:agent:{agent_id}:reload_sent")
        return data, reload_flag
    except Exception as e:
        print(f"  [redis error] {e}")
        return {}, None


def classify(signals):
    """Réplique de _resolve_agent_statuses_batch (server.py lignes 912-963)."""
    ctx           = int(signals.get("ctx", -1))
    is_compacting = signals.get("compacted") == "1"
    done_compact  = signals.get("done_compacting") == "1"
    ctx_limit     = signals.get("ctx_limit") == "1"
    api_error     = signals.get("api_error") == "1"
    has_bashes    = signals.get("has_bashes") == "1"
    busy          = signals.get("busy") == "1"
    plan_mode     = signals.get("plan_mode") == "1"
    wait_approval = signals.get("waiting_approval") == "1"
    claude_alive  = signals.get("claude_alive") == "1"

    if ctx_limit or api_error:
        return "needs_clear"
    if is_compacting and not done_compact:
        return "context_compacted"
    if ctx == 0 and not done_compact:
        return "context_compacted"
    if done_compact:
        if has_bashes:   return "has_bashes"
        if busy:         return "busy"
        return "active"
    if wait_approval:
        return "waiting_approval"
    if plan_mode:
        return "plan_mode"
    if not claude_alive:
        return "stopped"
    if has_bashes:
        return "has_bashes"
    if busy:
        return "busy"
    if 1 <= ctx <= 10:
        return "context_warning"
    if claude_alive:
        return "active"
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/debug-color.py <AGENT_ID>")
        print("Exemple: python3 scripts/debug-color.py 334-134")
        sys.exit(1)

    agent_id = sys.argv[1]
    session  = f"{MA_PREFIX}-agent-{agent_id}"

    print(f"\n{'='*65}")
    print(f"  AGENT {agent_id}   SESSION {session}")
    print(f"{'='*65}")

    # ── 1. tmux ──────────────────────────────────────────────────────────
    print("\n[1/3] CAPTURE TMUX  (capture-pane -S -30, dernières 20 lignes)")
    print("─" * 65)
    raw_output = detect_tmux(agent_id)
    raw_lines, signals = parse_output(raw_output)
    print("\n".join(raw_lines))

    # ── 2. signaux ───────────────────────────────────────────────────────
    print("\n[2/3] SIGNAUX DÉTECTÉS")
    print("─" * 65)
    for k, v in signals.items():
        marker = "  ←" if v == "1" else ""
        if k == "bp_line":
            print(f"  {k:<22} = {repr(v)}")
        else:
            print(f"  {k:<22} = {v}{marker}")

    # ── 3. redis ─────────────────────────────────────────────────────────
    print("\n[3/3] REDIS")
    print("─" * 65)
    redis_data, reload_flag = get_redis(agent_id)
    redis_status = redis_data.get("status", "active")
    print(f"  status               = {redis_status}")
    print(f"  reload_sent flag     = {reload_flag}")
    print(f"  queue_size           = {redis_data.get('queue_size', '?')}")
    print(f"  tasks_completed      = {redis_data.get('tasks_completed', '?')}")

    # ── 4. résolution ────────────────────────────────────────────────────
    CRITICAL = {"needs_clear", "context_compacted", "context_warning"}
    tmux_override = classify(signals)

    # Même règle que server.py lignes 287-294
    if tmux_override:
        if redis_status == "stopped" and tmux_override not in CRITICAL:
            final_status = "stopped"
        else:
            final_status = tmux_override
    else:
        final_status = redis_status

    color = COLOR_MAP.get(final_status, f"INCONNU ({final_status})")

    print(f"\n{'='*65}")
    print(f"  tmux override        → {tmux_override or '(aucun)'}")
    print(f"  redis status         → {redis_status}")
    print(f"  STATUT FINAL         → {final_status}")
    print(f"  COULEUR DASHBOARD    → {color}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
