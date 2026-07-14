"""Cache de fond du dashboard : tmux + Redis → state._cache (B1).

Tous les endpoints de lecture servent depuis ce cache ; une tâche de fond
le rafraîchit (15s nominal, 3s quand un agent approche la fin de compaction).
"""

import asyncio
import json
import os
import re
import time
from pathlib import Path

import redis.asyncio as redis

from . import config as cfg
from . import state
from .events import _log_event

# E1 : couche moteur — cfg a déjà inséré scripts/agent-bridge dans sys.path.
# Le scan de pane est GÉNÉRÉ depuis markers.<cli>.yaml : plus aucune chaîne
# d'UI en dur ici (c'était la 2e des trois copies du même parsing).
import engines  # noqa: E402


# Cache moteur/agent : la résolution lit prompts/ sur disque ; la boucle du
# dashboard tourne en continu. Invalidé par TTL court (un changement de modèle
# n'a d'effet qu'au redémarrage de l'agent, de toute façon).
_ENGINE_CACHE = {}
_ENGINE_CACHE_TS = 0.0
_ENGINE_CACHE_TTL = 30.0

# Un seul avertissement par moteur non relevé (sinon la boucle spamme les logs)
_MARKERS_WARNED = {}


def _agent_engine(agent_id):
    """Moteur d'un agent (inféré du modèle). Repli sur le défaut si prompts/ est
    illisible : mieux vaut le comportement historique qu'une exception dans la
    boucle de rafraîchissement du dashboard."""
    global _ENGINE_CACHE_TS
    now = time.time()
    if now - _ENGINE_CACHE_TS > _ENGINE_CACHE_TTL:
        _ENGINE_CACHE.clear()
        _ENGINE_CACHE_TS = now
    if agent_id not in _ENGINE_CACHE:
        try:
            _ENGINE_CACHE[agent_id] = engines.agent_engine(cfg.BASE_DIR / "prompts", agent_id)
        except Exception:
            _ENGINE_CACHE[agent_id] = engines.ENGINE_DEFAULT
    return _ENGINE_CACHE[agent_id]
from .prompts import _find_agent_prompt
from .tmuxio import _run_subprocess

# B6: pane states are published by each bridge (heartbeat 10s); beyond this
# age the dashboard falls back to a direct tmux scan for that agent.
PANE_STATE_TTL = int(os.environ.get("PANE_STATE_TTL", "30"))


def _pane_states_from_redis(agent_ids, agent_redis_data, now):
    """B6: read bridge-published pane states; return (states, stale_ids)."""
    states, stale = {}, []
    for aid in agent_ids:
        data = agent_redis_data.get(aid, {})
        raw = data.get("pane_state")
        ts = data.get("pane_state_ts")
        try:
            fresh = raw and ts and (now - int(ts)) <= PANE_STATE_TTL
        except (TypeError, ValueError):
            fresh = False
        if fresh:
            try:
                states[aid] = json.loads(raw)
                continue
            except (json.JSONDecodeError, TypeError):
                pass
        stale.append(aid)
    return states, stale


async def _trigger_prompt_reload(agent_id: str):
    """Send 'deviens agent' + last prompt via tmux send-keys after compacting (1x, debounced 60s)."""
    debounce_key = f"{cfg.MA_PREFIX}:agent:{agent_id}:last_reload"
    try:
        if state.redis_pool:
            last = await state.redis_pool.get(debounce_key)
            if last and time.time() - float(last) < 60:
                return  # debounce: too soon
            await state.redis_pool.set(debounce_key, str(time.time()), ex=120)

        # Find prompt file for this agent
        prompts_dir = cfg.BASE_DIR / "prompts"
        prompt_path = _find_agent_prompt(prompts_dir, agent_id)
        if not prompt_path:
            print(f"[reload] No prompt file found for agent {agent_id}")
            return
        session = f"{cfg.MA_PREFIX}-agent-{agent_id}"
        cmd = f"deviens agent {prompt_path}"

        # Read last prompt from .history file
        last_history = ""
        try:
            history_file = prompt_path.parent / f"{agent_id}.history"
            if history_file.exists():
                for line in reversed(history_file.read_text().strip().split('\n')):
                    if line and line[:4].isdigit() and ' | ' in line[:25]:
                        last_history = line
                        break
        except Exception:
            pass

        # Send text then C-m (Enter) separately to avoid lost keystrokes
        await _run_subprocess(
            ["tmux", "send-keys", "-t", f"{session}:0.0", "-l", cmd],
            text=True, timeout=5
        )
        await asyncio.sleep(0.3)
        result = await _run_subprocess(
            ["tmux", "send-keys", "-t", f"{session}:0.0", "C-m"],
            text=True, timeout=5
        )
        if result.returncode == 0:
            _log_event(agent_id, "deviens_agent", prompt_path.name)
            print(f"[reload] Sent 'deviens agent' to {agent_id} ({prompt_path.name})")
        else:
            print(f"[reload] Failed tmux send-keys for {agent_id}: {result.stderr}")
            return

        # Send context reminder after Claude finishes processing "deviens agent"
        if last_history:
            asyncio.ensure_future(_send_reload_context(session, agent_id, last_history))

    except Exception as e:
        print(f"[reload] Error for {agent_id}: {e}")


async def _send_reload_context(session: str, agent_id: str, last_history: str):
    """Wait for Claude to finish 'deviens agent', then send last prompt as context reminder."""
    target = f"{session}:0.0"
    try:
        # Poll tmux pane for prompt marker (up to 180s)
        for _ in range(36):
            await asyncio.sleep(5)
            pane = await _run_subprocess(
                ["tmux", "capture-pane", "-t", target, "-p", "-S", "-5"],
                text=True, timeout=5
            )
            if not pane.stdout:
                continue
            tail = pane.stdout.strip().split('\n')
            tail3 = ' '.join(line.strip() for line in tail[-3:] if line.strip())
            try:
                _m = engines.load_markers(_agent_engine(aid))
                _at_prompt = _m['status_line'] in tail3 or _m['plan_mode'] in tail3
            except RuntimeError:
                _at_prompt = False   # marqueurs du moteur non relevés → on s'abstient
            if _at_prompt:
                # Le CLI est au prompt — envoi du rappel de contexte
                reminder = f'Dernière ligne de ton historique : "{last_history}"\nContinue.'
                await _run_subprocess(
                    ["tmux", "send-keys", "-t", target, "C-u"],
                    text=True, timeout=5
                )
                await asyncio.sleep(0.3)
                await _run_subprocess(
                    ["tmux", "send-keys", "-t", target, "-l", reminder],
                    text=True, timeout=5
                )
                await asyncio.sleep(0.3)
                await _run_subprocess(
                    ["tmux", "send-keys", "-t", target, "C-m"],
                    text=True, timeout=5
                )
                _log_event(agent_id, "reload_context", last_history[:80])
                print(f"[reload] Sent context reminder to {agent_id}: {last_history[:60]}...")
                return
        print(f"[reload] Timeout waiting for prompt on {agent_id}, context reminder skipped")
    except Exception as e:
        print(f"[reload] Context reminder error for {agent_id}: {e}")


async def _resolve_agent_statuses_batch(agents_data: list) -> dict:
    """Batch resolve agent statuses using Redis pipelines.

    agents_data: list of (agent_id, tmux_state)
    tmux_state has: busy, compacted, context_pct, done_compacting, prompt_loaded

    Status logic:
      - compacting in progress (not done) → context_compacted (red), set flag, DON'T reload yet
      - done_compacting + prompt_loaded → green (prompt retained, no reload needed)
      - done_compacting + NOT prompt_loaded → send "deviens agent" (prompt lost)
      - context_pct 0% → context_compacted (red, compacting imminent)
      - context_pct 1-5% → context_warning (orange)

    Returns: dict of agent_id -> status override string
    """
    if not state.redis_pool or not agents_data:
        return {}

    overrides = {}

    try:
        # Step 1: GET reload_sent flags for ALL agents (single pipeline)
        pipe = state.redis_pool.pipeline()
        for aid, _ in agents_data:
            pipe.get(f"{cfg.MA_PREFIX}:agent:{aid}:reload_sent")
        reload_flags = await pipe.execute()

        # Step 2a: Detect transitions → log events
        for aid, st in agents_data:
            prev = state._prev_agent_states.get(aid, {})
            # compacting False→True
            if st.get('compacted') and not prev.get('compacted'):
                _log_event(aid, "compacting", "started")
            # api_error False→True
            if st.get('api_error') and not prev.get('api_error'):
                _log_event(aid, "api_error", "3+ API errors")
            # context_limit False→True
            if st.get('context_limit') and not prev.get('context_limit'):
                _log_event(aid, "context_limit", "reached")
            # model_change detected
            if st.get('model_change') and not prev.get('model_change'):
                _log_event(aid, "model", "/model detected in output")
            state._prev_agent_states[aid] = dict(st)

        # Step 2b: Classify agents + set compacting timestamp flag
        now = time.time()
        for i, (aid, st) in enumerate(agents_data):
            ctx = st.get('context_pct', -1)
            is_compacting = st.get('compacted', False)
            done_compacting = st.get('done_compacting', False)
            context_limit = st.get('context_limit', False)
            api_error = st.get('api_error', False)
            flag_ts = float(reload_flags[i]) if reload_flags[i] else 0

            if ctx >= 0 or is_compacting or done_compacting or context_limit or api_error:
                elapsed = int(now - flag_ts) if flag_ts else 0
                print(f"[context] Agent {aid}: ctx={ctx}% compacting={is_compacting} done={done_compacting} limit={context_limit} api_err={api_error} flag={elapsed}s")

            # Context limit reached OR repeated API errors — agent is STUCK, immediate /clear + reload
            if context_limit or api_error:
                overrides[aid] = "needs_clear"
                continue

            if is_compacting and not done_compacting:
                # Red: compacting in progress
                overrides[aid] = "context_compacted"
                if not flag_ts:
                    # Set timestamp flag (when compacting started)
                    await state.redis_pool.set(f"{cfg.MA_PREFIX}:agent:{aid}:reload_sent", str(now), ex=600)
            elif ctx == 0 and not done_compacting:
                # Red: context at 0%, compacting imminent — also set flag
                overrides[aid] = "context_compacted"
                if not flag_ts:
                    await state.redis_pool.set(f"{cfg.MA_PREFIX}:agent:{aid}:reload_sent", str(now), ex=600)
            elif done_compacting:
                # "Conversation compacted" visible → compacting finished
                if st.get('has_bashes'):
                    overrides[aid] = "has_bashes"
                elif st.get('busy'):
                    overrides[aid] = "busy"
                else:
                    overrides[aid] = "active"     # gray — idle after compacting, clear stale Redis
            elif st.get('waiting_approval'):
                overrides[aid] = "waiting_approval"  # blue — interactive prompt (Enter to select)
            elif st.get('plan_mode'):
                overrides[aid] = "plan_mode"      # dark blue — plan mode (awaiting user)
            elif not st.get('claude_alive', True):
                overrides[aid] = "stopped"        # dark gray — Claude process exited (bash/zsh in pane)
            elif st.get('has_bashes'):
                overrides[aid] = "has_bashes"     # dark green — bashes executing
            elif st.get('busy'):
                overrides[aid] = "busy"           # yellow — Claude running
            elif 1 <= ctx <= 10:
                # Orange: context running low (1-10%)
                overrides[aid] = "context_warning"
            elif st.get('claude_alive', True):
                overrides[aid] = "active"         # gray — Claude idle, neutralise Redis stale "busy"

        # Step 3: After compacting finished, verify prompt retention
        # Conditions: flag exists + not compacting anymore + ctx != 0 (context refreshed) + waited >= 80s
        clear_ids = []
        for i, (aid, st) in enumerate(agents_data):
            flag_ts = float(reload_flags[i]) if reload_flags[i] else 0
            if not flag_ts:
                continue
            ctx = st.get('context_pct', -1)
            is_compacting = st.get('compacted', False)
            prompt_loaded = st.get('prompt_loaded', False)
            elapsed = now - flag_ts

            # Still compacting or at ctx=0 waiting → skip
            if is_compacting or ctx == 0:
                continue
            # Not enough time elapsed → skip (compacting takes ~90-120s)
            if elapsed < cfg.COMPACTING_WAIT_SECS:
                continue

            # Compacting is done (flag set, not compacting, ctx refreshed, waited enough)
            if prompt_loaded:
                clear_ids.append(aid)
                print(f"[reload] Agent {aid}: prompt in output after compacting ({int(elapsed)}s), no reload needed")
            else:
                # Deep capture (100 lines) to check further back
                session = f"{cfg.MA_PREFIX}-agent-{aid}"
                deep = await _run_subprocess(
                    ["tmux", "capture-pane", "-t", f"{session}:0.0", "-p", "-J", "-S", "-100"],
                    text=True, timeout=5
                )
                deep_text = deep.stdout if deep and deep.stdout else ""
                # Check for prompt path in deep capture: both flat (prompts/345-) and x45 (prompts/380-*/380-980)
                parent_aid = aid.split('-')[0] if '-' in aid else aid
                if (f"prompts/{aid}-" in deep_text or
                    re.search(rf"prompts/{re.escape(parent_aid)}\S*/{re.escape(aid)}[.\-]", deep_text)):
                    clear_ids.append(aid)
                    print(f"[reload] Agent {aid}: prompt in deep capture ({int(elapsed)}s), no reload needed")
                else:
                    print(f"[reload] Agent {aid}: prompt NOT found ({int(elapsed)}s), sending deviens agent")
                    asyncio.ensure_future(_trigger_prompt_reload(aid))
                    clear_ids.append(aid)

        if clear_ids:
            pipe = state.redis_pool.pipeline()
            for aid in clear_ids:
                pipe.delete(f"{cfg.MA_PREFIX}:agent:{aid}:reload_sent")
            await pipe.execute()

    except Exception as e:
        print(f"[cache] batch status resolve error: {e}")

    return overrides


async def _refresh_cache_once():
    """Single cache refresh cycle: tmux + Redis → state._cache.

    Runs in background, never blocks API handlers.
    """
    now = int(time.time())

    # --- Health ---
    # redis state: "ok" | "noauth" | "down"
    # JWT is determined client-side (response status), not here.
    redis_state = "down"
    if state.redis_pool:
        try:
            await state.redis_pool.ping()
            redis_state = "ok"
        except redis.exceptions.AuthenticationError:
            redis_state = "noauth"
        except Exception as e:
            msg = str(e).lower()
            if "auth" in msg or "noauth" in msg or "wrongpass" in msg:
                redis_state = "noauth"
            else:
                redis_state = "down"

    health = {"status": "ok" if redis_state == "ok" else "degraded", "redis": redis_state, "timestamp": now}

    # --- Agent list (tmux sessions) ---
    agent_ids = []
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{session_name}"], text=True
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith(f"{cfg.MA_PREFIX}-agent-"):
                    agent_id = line.replace(f"{cfg.MA_PREFIX}-agent-", "")
                    # Accept numeric IDs (345) and compound IDs (345-500)
                    if cfg.is_valid_agent_id(agent_id):
                        agent_ids.append(agent_id)
    except Exception as e:
        print(f"[cache] agent list error: {e}")

    # --- Batch Redis enrichment (1 pipeline round-trip instead of N) ---
    agent_redis_data = {}
    if state.redis_pool and agent_ids:
        try:
            pipe = state.redis_pool.pipeline()
            for agent_id in agent_ids:
                pipe.hgetall(f"{cfg.MA_PREFIX}:agent:{agent_id}")
            results = await pipe.execute()
            for agent_id, data in zip(agent_ids, results):
                agent_redis_data[agent_id] = data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[cache] redis pipeline error: {e}")

    # --- Agent pane states: Redis first (published by the bridge, B6),
    #     tmux multi-grep scan only for agents with missing/stale pane_state ---
    agent_states, stale_ids = _pane_states_from_redis(agent_ids, agent_redis_data, now)
    if stale_ids:
      try:
        # E1 : scan GÉNÉRÉ depuis markers.<cli>.yaml, groupé par moteur.
        # Un agent dont les marqueurs UI ne sont pas relevés est ignoré ici :
        # son état viendra de Redis dès que son bridge aura publié (B6). Le
        # deviner produirait un état FAUX, et un faux état est pire qu'un état
        # absent (le dashboard le rafraîchit, il ne le corrige pas).
        by_engine = {}
        for aid in stale_ids:
            by_engine.setdefault(_agent_engine(aid), []).append(aid)

        for cli, ids in by_engine.items():
            try:
                markers = engines.load_markers(cli)
            except RuntimeError as e:
                if not _MARKERS_WARNED.get(cli):
                    print(f"[cache] moteur '{cli}' : scan tmux désactivé — {e}")
                    _MARKERS_WARNED[cli] = True
                continue

            script = engines.build_pane_scan(markers, cfg.MA_PREFIX)
            sessions = [f"{cfg.MA_PREFIX}-agent-{aid}" for aid in ids]
            result = await _run_subprocess(
                ["bash", "-c", script, "_", *sessions], text=True, timeout=60
            )
            for line in result.stdout.strip().split('\n'):
                if ':' not in line:
                    continue
                parts = line.split(':')
                if len(parts) < len(engines.PANE_FIELDS):
                    continue
                f = dict(zip(engines.PANE_FIELDS, parts))
                ctx_pct = int(f['context_pct']) if f['context_pct'].lstrip('-').isdigit() else -1
                agent_states[f['id']] = {
                    'busy': f['busy'] == '1',
                    'has_bashes': f['has_bashes'] == '1',
                    'has_down': f['has_down'] == '1',
                    'plan_mode': f['plan_mode'] == '1',
                    'waiting_approval': f['waiting_approval'] == '1',
                    'compacted': f['compacted'] == '1',
                    'context_pct': ctx_pct,   # -1 = non affiché par le CLI
                    'done_compacting': f['done_compacting'] == '1',
                    'prompt_loaded': f['prompt_loaded'] == '1',
                    'context_limit': f['context_limit'] == '1',
                    'api_error': f['api_error'] == '1',
                    'model_change': f['model_change'] == '1',
                    'claude_alive': f['claude_alive'] == '1',
                }
      except Exception as e:
        print(f"[cache] tmux states error: {e}")

    # --- Batch XLEN inbox for prompt detection ---
    if state.redis_pool and agent_ids:
        try:
            pipe = state.redis_pool.pipeline()
            for agent_id in agent_ids:
                pipe.xlen(f"{cfg.MA_PREFIX}:agent:{agent_id}:inbox")
            xlens = await pipe.execute()
            for agent_id, xlen in zip(agent_ids, xlens):
                xlen = int(xlen) if isinstance(xlen, (int, str)) else 0
                prev_xlen = state._prev_inbox_xlens.get(agent_id, 0)
                if xlen > prev_xlen and prev_xlen > 0:
                    for _ in range(xlen - prev_xlen):
                        _log_event(agent_id, "prompt", f"xlen {prev_xlen}→{xlen}")
                state._prev_inbox_xlens[agent_id] = xlen
        except Exception as e:
            print(f"[cache] inbox xlen error: {e}")

    # --- Batch resolve agent statuses (3-5 pipeline round-trips instead of 3N-5N) ---
    status_overrides = await _resolve_agent_statuses_batch(
        [(aid, agent_states.get(aid, {}))
         for aid in agent_ids]
    )

    # --- Build agent list ---
    # context_compacted removed: when redis_status=="stopped", stopped wins (gray bg + red border via ctx=0)
    CRITICAL_OVERRIDES = {"needs_clear", "context_warning"}
    agents = []
    for agent_id in agent_ids:
        data = agent_redis_data.get(agent_id, {})
        redis_status = data.get("status", "active")
        status = redis_status
        override = status_overrides.get(agent_id)
        if override:
            # Redis "stopped" wins over cosmetic overrides (busy, has_bashes, etc.)
            # but not over critical ones (needs_clear, context_warning)
            if redis_status == "stopped" and override not in CRITICAL_OVERRIDES:
                pass  # keep "stopped"
            elif override == "stopped" and redis_status not in ("stopped", ""):
                status = "error"  # tmux dead but Redis still active/busy → crash
            else:
                status = override

        st = agent_states.get(agent_id, {})
        agents.append({
            "id": agent_id,
            "status": status,
            "ctx": st.get('context_pct', -1),
            "has_down": st.get('has_down', False),
            "last_seen": int(data.get("last_seen", 0)) or now,
            "queue_size": int(data.get("queue_size", 0)),
            "tasks_completed": int(data.get("tasks_completed", 0)),
            "mode": "tmux",
        })

    agents.sort(key=lambda a: tuple(int(p) for p in a["id"].split("-")))

    # --- Detect x45 mode + extract agent names ---
    prompts_dir = cfg.BASE_DIR / "prompts"
    x45_dirs = []  # list of (numeric_id, dir_path)
    agent_names = {}  # id -> human name (e.g. "301" -> "build frontend")

    # From directories: 301-build-frontend/, 900-architect-chat/, etc.
    for d in prompts_dir.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r'^(\d{3})(?:-(.+))?$', d.name)
        if not m:
            continue
        did = m.group(1)
        if m.group(2):
            import html as _html
            agent_names[did] = _html.escape(m.group(2).replace("-", " "))
        # Detect x45/z21 by agent.type or by compound system.md presence
        type_link = d / "agent.type"
        agent_type = ""
        if type_link.is_symlink():
            agent_type = Path(os.readlink(type_link)).stem.replace("agent_", "")
        if agent_type in ("x45", "z21") or (d / f"{did}-{did}-system.md").exists():
            x45_dirs.append((did, d))

    # From flat .md files (legacy): 900-architect-chat.md
    for f in prompts_dir.iterdir():
        if not f.is_file() or f.suffix != ".md":
            continue
        m = re.match(r'^(\d{3})-(.+)\.md$', f.name)
        if m and m.group(1) not in agent_names:
            agent_names[m.group(1)] = m.group(2).replace("-", " ")

    mode = "x45" if x45_dirs else "pipeline"

    triangles = {}
    if mode == "x45":
        for did, d in x45_dirs:
            tri = {"worker": f"{did}-{did}"}
            # Scan system.md files (local) + .remote files (remote agents)
            sat_entries = []
            for f in d.glob(f"{did}-*-system.md"):
                suffix = f.stem.replace(f"{did}-", "", 1).replace("-system", "")
                sat_entries.append(suffix)
            for f in d.glob(f"{did}-*.remote"):
                suffix = f.stem.replace(f"{did}-", "", 1)
                if suffix not in [s for s in sat_entries]:
                    sat_entries.append(suffix)
            for suffix in sat_entries:
                if not suffix or not suffix[0].isdigit():
                    continue
                role_digit = suffix[0]
                sat_id = f"{did}-{suffix}"
                if role_digit == "3":
                    tri["worker"] = sat_id
                elif role_digit == "1":
                    tri["master"] = sat_id
                elif role_digit == "5":
                    tri["observer"] = sat_id
                elif role_digit == "6":
                    tri["indexer"] = sat_id
                elif role_digit == "7":
                    tri["curator"] = sat_id
                elif role_digit == "8":
                    tri["coach"] = sat_id
                elif role_digit == "9":
                    tri["tri_architect"] = sat_id
            # Read type from agent.type symlink
            type_link = d / "agent.type"
            if type_link.is_symlink():
                tri["type"] = Path(os.readlink(type_link)).stem.replace("agent_", "")
            else:
                tri["type"] = "x45"
            triangles[did] = tri

    # --- Write cache atomically ---
    async with state._cache_lock:
        state._cache["agents"] = agents
        state._cache["health"] = health
        state._cache["mode"] = mode
        state._cache["triangles"] = triangles
        state._cache["agent_names"] = agent_names
        state._cache["timestamp"] = now


async def _cache_loop():
    """Background loop with adaptive polling: fast (3s) when agents near compacting end, normal (15s) otherwise."""
    while True:
        try:
            await _refresh_cache_once()
        except Exception as e:
            print(f"[cache] refresh error: {e}")
        # Adaptive interval: check if any agent needs fast polling
        interval = cfg.CACHE_REFRESH_INTERVAL
        try:
            if state.redis_pool:
                # Scan for any reload_sent timestamps where elapsed >= COMPACTING_WAIT_SECS
                keys = []
                async for key in state.redis_pool.scan_iter(match=f"{cfg.MA_PREFIX}:agent:*:reload_sent", count=100):
                    keys.append(key)
                for key in keys:
                    ts = await state.redis_pool.get(key)
                    if ts:
                        elapsed = time.time() - float(ts)
                        if elapsed >= cfg.COMPACTING_WAIT_SECS:
                            interval = cfg.CACHE_FAST_INTERVAL
                            break
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _seed_prompt_history():
    """Load existing .history files into Redis stream on startup."""
    if not state.redis_pool:
        return
    try:
        existing = await state.redis_pool.xlen(cfg.PROMPT_HISTORY_STREAM)
        if existing > 0:
            return  # already seeded
        prompts_dir = cfg.BASE_DIR / "prompts"
        all_entries = []
        for hf in prompts_dir.glob("**/*.history"):
            # Extract agent ID from filename (e.g. 305.history -> 305)
            agent_id = hf.stem.split('-')[0]
            for line in hf.read_text(errors="replace").splitlines():
                if " | " not in line:
                    continue
                ts_part, text_part = line.split(" | ", 1)
                ts_part = ts_part.strip()
                # Parse "YYYY-MM-DD HH:MM:SS"
                hm = ts_part[11:16] if len(ts_part) >= 16 else ts_part
                all_entries.append((ts_part, hm, agent_id, text_part[:20]))
        all_entries.sort(key=lambda x: x[0])
        for _, hm, agent, text in all_entries[-50:]:
            await state.redis_pool.xadd(
                cfg.PROMPT_HISTORY_STREAM,
                {"time": hm, "agent": agent, "text": text},
                maxlen=50,
            )
        if all_entries:
            print(f"Seeded prompt history: {min(len(all_entries), 50)} entries")
    except Exception as e:
        print(f"WARNING: Failed to seed prompt history: {e}")
