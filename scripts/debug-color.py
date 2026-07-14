#!/usr/bin/env python3
"""
debug-color.py — détecte la couleur qu'afficherait le dashboard pour un agent

Réplique exacte de la logique server.py :
  - tmux capture-pane -S -30  (MÊME script bash, généré depuis les marqueurs)
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
from pathlib import Path

# E1 : couche moteur — le script bash est GÉNÉRÉ depuis markers.<cli>.yaml.
# C'était la 3e copie du même parsing de pane, avec ses chaînes d'UI en dur.
sys.path.insert(0, str(Path(__file__).resolve().parent / "agent-bridge"))
import engines  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
MA_PREFIX = os.environ.get("MA_PREFIX", "A")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")

# AgentGrid.jsx getStatusColor()
COLOR_MAP = {
    "has_bashes":        "VERT          (has_bashes)       — bashes arrière-plan",
    "busy":              "VERT CLAIR    (busy)             — Claude traite un prompt",
    "waiting_approval":  "BLEU          (waiting_approval) — menu de sélection ouvert",
    "plan_mode":         "BLEU FONCÉ   (plan_mode)        — mode plan actif",
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
    """Réplique EXACTE du scan du dashboard : même générateur, mêmes marqueurs.

    Avant E1, cette fonction recopiait à la main le blob bash de cache.py. Les
    deux ont dérivé — c'est ainsi qu'un outil de diagnostic finit par mentir.
    Elles partagent désormais engines.build_pane_eval().
    """
    session = f"{MA_PREFIX}-agent-{agent_id}"
    cli = engines.agent_engine(BASE_DIR / "prompts", agent_id)
    markers = engines.load_markers(cli)   # fail-fast si non relevés

    script = (
        f's="{session}"; id="{agent_id}"; '
        'out=$(tmux capture-pane -t "$s:0.0" -p -J -S -30 2>/dev/null); '
        'pane_cmd=$(tmux display-message -t "$s:0.0" -p "#{pane_current_command}" '
        '2>/dev/null || echo ""); '
        'printf "===RAW===\\n"; printf "%s\\n" "$out" | tail -20; '
        'printf "===META===\\n"; '
        f'echo "cli={cli}"; echo "pane_cmd=$pane_cmd"; echo "bp_line=$bp_line"; '
        'printf "===STATE===\\n"; '
        + engines.build_pane_eval(markers)
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout


# Alias : noms de champs du générateur → noms attendus par classify()
_FIELD_ALIAS = {"context_pct": "ctx", "context_limit": "ctx_limit"}


def parse_output(output):
    """Découpe la sortie de detect_tmux en (lignes brutes, signaux).

    La section ===STATE=== porte la ligne compacte à 14 champs produite par
    engines.build_pane_eval() — la MÊME que celle consommée par cache.py.
    """
    raw_lines = []
    signals = {}
    section = None
    for line in output.split("\n"):
        if line == "===RAW===":
            section = "raw"
            continue
        if line == "===META===":
            section = "meta"
            continue
        if line == "===STATE===":
            section = "state"
            continue
        if section == "raw":
            raw_lines.append(line)
        elif section == "meta" and "=" in line:
            k, _, v = line.partition("=")
            signals[k.strip()] = v.strip()
        elif section == "state" and ":" in line:
            parts = line.split(":")
            if len(parts) < len(engines.PANE_FIELDS):
                continue
            for name, value in zip(engines.PANE_FIELDS, parts):
                signals[_FIELD_ALIAS.get(name, name)] = value
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
        elif tmux_override == "stopped" and redis_status not in ("stopped", ""):
            final_status = "error"
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
