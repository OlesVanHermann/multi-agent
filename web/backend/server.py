#!/usr/bin/env python3
"""
Multi-Agent Dashboard Backend
FastAPI server exposing agent status and WebSocket streams
"""

import os
import re
import asyncio
import time
import subprocess
import concurrent.futures
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import json

import redis.asyncio as redis
import httpx

# Dedicated thread pool for subprocess calls (tmux).
# Default asyncio pool is only 20 threads — easily saturated by WS handlers
# each doing 2x subprocess.run per tick. 64 threads handles up to ~30 concurrent
# WS connections without starvation.
_tmux_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=64, thread_name_prefix="tmux"
)


async def _run_subprocess(cmd, **kwargs):
    """Run subprocess in dedicated thread pool. Never blocks the asyncio default pool."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("timeout", 5)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _tmux_executor, lambda: subprocess.run(cmd, **kwargs)
    )

# Frontend static files path
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "../frontend/dist")

# Keycloak URL for auth proxy
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")

# Config
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "A")
BASE_DIR = Path(os.environ.get("MA_BASE", Path.home() / "multi-agent"))

# Redis connection pool
redis_pool: Optional[redis.Redis] = None


# === Background Cache ===
# All read endpoints serve from this cache. A background task refreshes it.
CACHE_REFRESH_INTERVAL = int(os.environ.get("CACHE_REFRESH_INTERVAL", "15"))  # seconds (normal)
CACHE_FAST_INTERVAL = 3  # seconds (when agent near compacting end)
COMPACTING_WAIT_SECS = 80  # wait this long before fast-polling for compacting end

_cache = {
    "agents": [],       # list of agent dicts
    "health": {"status": "starting", "redis": False, "timestamp": 0},
    "mode": "pipeline", # "pipeline" or "x45"
    "triangles": {},    # {worker_id: {worker, curator, coach}}
    "timestamp": 0,     # last refresh epoch
}
_cache_lock = asyncio.Lock()
_cache_task: Optional[asyncio.Task] = None

# === Event Logging ===
# Track previous states for transition detection
_prev_agent_states: dict[str, dict] = {}
_prev_inbox_xlens: dict[str, int] = {}


def _events_dir(agent_id: str) -> Path:
    """Return logs/{agent_id}/ directory, create if needed."""
    d = BASE_DIR / "logs" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_event(agent_id: str, event_type: str, detail: str = ""):
    """Append JSON line to logs/{agent_id}/events.jsonl."""
    from datetime import datetime
    entry = json.dumps({"ts": datetime.now().strftime("%Y%m%d_%H%M%S"), "type": event_type, "detail": detail})
    try:
        f = _events_dir(agent_id) / "events.jsonl"
        with open(f, "a") as fh:
            fh.write(entry + "\n")
        print(f"[event] agent={agent_id} type={event_type} detail={detail}")
    except Exception as e:
        print(f"[event] log error agent={agent_id}: {e}")


def _rotate_events(agent_id: str):
    """Rotate events on /clear: rename events.jsonl → events.{timestamp}.jsonl."""
    try:
        d = _events_dir(agent_id)
        current = d / "events.jsonl"
        if current.exists() and current.stat().st_size > 0:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archived = d / f"events.{ts}.jsonl"
            current.rename(archived)
            print(f"[event] rotated events for agent {agent_id} → {archived.name}")
        else:
            print(f"[event] nothing to rotate for agent {agent_id}")
    except Exception as e:
        print(f"[event] rotate error agent={agent_id}: {e}")


async def _refresh_cache_once():
    """Single cache refresh cycle: tmux + Redis → _cache.

    Runs in background, never blocks API handlers.
    """
    global _cache

    now = int(time.time())

    # --- Health ---
    redis_ok = False
    if redis_pool:
        try:
            await redis_pool.ping()
            redis_ok = True
        except Exception:
            pass

    health = {"status": "ok" if redis_ok else "degraded", "redis": redis_ok, "timestamp": now}

    # --- Agent tmux states (sequential for loop, single capture per agent) ---
    agent_states = {}
    try:
        # Single capture -S -30 per agent (not 2x -S -200) = 30x less data.
        script = (
            'for s in $(tmux ls -F "#{session_name}" 2>/dev/null | grep "^' + MA_PREFIX + '-agent-"); do '
            'id="${s#' + MA_PREFIX + '-agent-}"; '
            'out=$(tmux capture-pane -t "$s:0.0" -p -J -S -30 2>/dev/null); '
            'busy=0; has_bashes=0; has_down=0; plan_mode=0; compacted=0; ctx=-1; done_compacting=0; prompt_loaded=0; ctx_limit=0; api_error=0; model_change=0; '
            'bp_line=$(echo "$out" | grep "bypass permissions" | tail -1); '
            'if echo "$bp_line" | grep -q "bashes"; then has_bashes=1; fi; '
            'if echo "$bp_line" | grep -q "esc"; then busy=1; fi; '
            'if echo "$bp_line" | grep -q "↓"; then has_down=1; fi; '
            'if echo "$out" | grep -q "plan mode on"; then plan_mode=1; fi; '
            'waiting_approval=0; '
            'if echo "$out" | grep -q "Enter to select"; then waiting_approval=1; fi; '
            'if echo "$out" | grep -qiE "compacting conversation"; then compacted=1; fi; '
            'if echo "$out" | grep -qi "Conversation compacted"; then done_compacting=1; fi; '
            'if [ "$done_compacting" -eq 1 ] && echo "$out" | grep -qE "prompts/[0-9]+/${id}[.-]|prompts/${id}-"; then prompt_loaded=1; fi; '
            'pct=$(echo "$out" | grep -oE "auto-compact: [0-9]+%" | tail -1 | grep -oE "[0-9]+"); '
            'if [ -n "$pct" ]; then ctx=$pct; fi; '
            'if echo "$out" | grep -q "Context limit reached"; then ctx_limit=1; fi; '
            'api_err_count=$(echo "$out" | grep -c "API Error:" 2>/dev/null || echo 0); '
            'if [ "$api_err_count" -ge 3 ]; then api_error=1; fi; '
            'if echo "$out" | grep -q "/model "; then model_change=1; fi; '
            'echo "$id:$busy:$compacted:$ctx:$done_compacting:$prompt_loaded:$ctx_limit:$api_error:$model_change:$has_bashes:$plan_mode:$has_down:$waiting_approval"; '
            'done'
        )
        result = await _run_subprocess(
            ["bash", "-c", script], text=True, timeout=60
        )
        for line in result.stdout.strip().split('\n'):
            if ':' not in line:
                continue
            parts = line.split(':')
            if len(parts) >= 4:
                ctx_pct = int(parts[3]) if parts[3].lstrip('-').isdigit() else -1
                done_compacting = parts[4] == '1' if len(parts) >= 5 else False
                prompt_loaded = parts[5] == '1' if len(parts) >= 6 else False
                ctx_limit = parts[6] == '1' if len(parts) >= 7 else False
                api_error = parts[7] == '1' if len(parts) >= 8 else False
                model_change = parts[8] == '1' if len(parts) >= 9 else False
                has_bashes = parts[9] == '1' if len(parts) >= 10 else False
                plan_mode = parts[10] == '1' if len(parts) >= 11 else False
                has_down = parts[11] == '1' if len(parts) >= 12 else False
                waiting_approval = parts[12] == '1' if len(parts) >= 13 else False
                agent_states[parts[0]] = {
                    'busy': parts[1] == '1',
                    'compacted': parts[2] == '1',
                    'context_pct': ctx_pct,  # -1 = not visible, 0-5 = shown by Claude
                    'done_compacting': done_compacting,
                    'prompt_loaded': prompt_loaded,
                    'context_limit': ctx_limit,
                    'api_error': api_error,
                    'model_change': model_change,
                    'has_bashes': has_bashes,
                    'has_down': has_down,
                    'plan_mode': plan_mode,
                    'waiting_approval': waiting_approval,
                }
    except Exception as e:
        print(f"[cache] tmux states error: {e}")

    # --- Agent list (tmux sessions) ---
    agent_ids = []
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{session_name}"], text=True
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith(f"{MA_PREFIX}-agent-"):
                    agent_id = line.replace(f"{MA_PREFIX}-agent-", "")
                    # Accept numeric IDs (345) and compound IDs (345-500)
                    if re.match(r'^\d{3}(-\d{3})?$', agent_id):
                        agent_ids.append(agent_id)
    except Exception as e:
        print(f"[cache] agent list error: {e}")

    # --- Batch Redis enrichment (1 pipeline round-trip instead of N) ---
    agent_redis_data = {}
    if redis_pool and agent_ids:
        try:
            pipe = redis_pool.pipeline()
            for agent_id in agent_ids:
                pipe.hgetall(f"{MA_PREFIX}:agent:{agent_id}")
            results = await pipe.execute()
            for agent_id, data in zip(agent_ids, results):
                agent_redis_data[agent_id] = data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[cache] redis pipeline error: {e}")

    # --- Batch XLEN inbox for prompt detection ---
    if redis_pool and agent_ids:
        try:
            pipe = redis_pool.pipeline()
            for agent_id in agent_ids:
                pipe.xlen(f"{MA_PREFIX}:agent:{agent_id}:inbox")
            xlens = await pipe.execute()
            for agent_id, xlen in zip(agent_ids, xlens):
                xlen = int(xlen) if isinstance(xlen, (int, str)) else 0
                prev_xlen = _prev_inbox_xlens.get(agent_id, 0)
                if xlen > prev_xlen and prev_xlen > 0:
                    for _ in range(xlen - prev_xlen):
                        _log_event(agent_id, "prompt", f"xlen {prev_xlen}→{xlen}")
                _prev_inbox_xlens[agent_id] = xlen
        except Exception as e:
            print(f"[cache] inbox xlen error: {e}")

    # --- Batch resolve agent statuses (3-5 pipeline round-trips instead of 3N-5N) ---
    status_overrides = await _resolve_agent_statuses_batch(
        [(aid, agent_states.get(aid, {}))
         for aid in agent_ids]
    )

    # --- Build agent list ---
    agents = []
    for agent_id in agent_ids:
        data = agent_redis_data.get(agent_id, {})
        status = data.get("status", "active")
        override = status_overrides.get(agent_id)
        if override:
            status = override

        state = agent_states.get(agent_id, {})
        agents.append({
            "id": agent_id,
            "status": status,
            "has_down": state.get('has_down', False),
            "last_seen": int(data.get("last_seen", 0)) or now,
            "queue_size": int(data.get("queue_size", 0)),
            "tasks_completed": int(data.get("tasks_completed", 0)),
            "mode": "tmux",
        })

    agents.sort(key=lambda a: tuple(int(p) for p in a["id"].split("-")))

    # --- Detect x45 mode + extract agent names ---
    prompts_dir = BASE_DIR / "prompts"
    x45_dirs = []  # list of (numeric_id, dir_path)
    agent_names = {}  # id -> human name (e.g. "301" -> "build frontend")

    # From directories: 301-build-frontend/
    for d in prompts_dir.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r'^(\d{3})(?:-(.+))?$', d.name)
        if not m:
            continue
        did = m.group(1)
        if m.group(2):
            agent_names[did] = m.group(2).replace("-", " ")
        if (d / f"{did}-system.md").exists():
            x45_dirs.append((did, d))

    # From flat .md files: 900-architect-chat.md (only if not already named by dir)
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
            tri = {"worker": did}
            for f in d.glob(f"{did}-*-system.md"):
                suffix = f.stem.replace(f"{did}-", "", 1).replace("-system", "")
                if not suffix or not suffix[0].isdigit():
                    continue
                role_digit = suffix[0]
                sat_id = f"{did}-{suffix}"
                if role_digit == "1":
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
            triangles[did] = tri

    # --- Write cache atomically ---
    async with _cache_lock:
        _cache["agents"] = agents
        _cache["health"] = health
        _cache["mode"] = mode
        _cache["triangles"] = triangles
        _cache["agent_names"] = agent_names
        _cache["timestamp"] = now


async def _cache_loop():
    """Background loop with adaptive polling: fast (3s) when agents near compacting end, normal (15s) otherwise."""
    while True:
        try:
            await _refresh_cache_once()
        except Exception as e:
            print(f"[cache] refresh error: {e}")
        # Adaptive interval: check if any agent needs fast polling
        interval = CACHE_REFRESH_INTERVAL
        try:
            if redis_pool:
                # Scan for any reload_sent timestamps where elapsed >= COMPACTING_WAIT_SECS
                keys = await redis_pool.keys(f"{MA_PREFIX}:agent:*:reload_sent")
                for key in keys:
                    ts = await redis_pool.get(key)
                    if ts:
                        elapsed = time.time() - float(ts)
                        if elapsed >= COMPACTING_WAIT_SECS:
                            interval = CACHE_FAST_INTERVAL
                            break
        except Exception:
            pass
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events"""
    global redis_pool, _cache_task
    redis_pool = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True
    )
    try:
        await redis_pool.ping()
        print(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
    except Exception as e:
        print(f"WARNING: Redis connection failed: {e}")

    # Start background cache refresh
    _cache_task = asyncio.create_task(_cache_loop())
    print(f"Background cache started (refresh every {CACHE_REFRESH_INTERVAL}s)")

    yield

    # Stop background cache
    if _cache_task:
        _cache_task.cancel()
        try:
            await _cache_task
        except asyncio.CancelledError:
            pass

    if redis_pool:
        await redis_pool.close()


app = FastAPI(
    title="Multi-Agent Dashboard API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Models ===

class AgentStatus(BaseModel):
    id: str
    status: str = "unknown"
    last_seen: int = 0
    queue_size: int = 0
    tasks_completed: int = 0
    mode: str = "unknown"


class SendMessage(BaseModel):
    message: str
    from_agent: str = "web"


class LoginModelUpdate(BaseModel):
    agent_id: str      # "300" or "default"
    type: str          # "login" or "model"
    value: str         # "claude2a" or "" to remove override


# === Routes ===

@app.get("/api/health")
async def health():
    """Health check — reads from background cache"""
    return _cache["health"]


# _get_agent_states removed — replaced by background _cache_loop


def _resolve_prompts_dir(prompts_dir: Path, numeric_id: str) -> Optional[Path]:
    """Resolve a numeric agent ID to its prompts directory.
    Handles both plain (345/) and named (345-develop-fonction-beta/) directories.
    """
    # Exact match first
    exact = prompts_dir / numeric_id
    if exact.is_dir():
        return exact
    # Named directory: 345-*
    for d in prompts_dir.iterdir():
        if d.is_dir() and re.match(rf'^{re.escape(numeric_id)}-', d.name):
            return d
    return None


def _find_agent_prompt(prompts_dir: Path, agent_id: str) -> Optional[Path]:
    """Find prompt file for an agent. Supports:
    - x45 new: prompts/{parent}*/{id}.md (e.g. prompts/345/345-500.md)
    - x45 old: prompts/{id}/system.md
    - flat: prompts/{id}-*.md
    Handles named directories (345-develop-fonction-beta/).
    """
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    # x45: resolve named directory
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    if parent_dir:
        entry = parent_dir / f"{agent_id}.md"
        if entry.exists():
            return entry
    # Flat format
    matches = sorted(prompts_dir.glob(f"{agent_id}-*.md"))
    if matches:
        return matches[0]
    return None


async def _trigger_context_clear(agent_id: str):
    """Send /clear then 'deviens agent' when Context limit reached (agent is stuck)."""
    debounce_key = f"{MA_PREFIX}:agent:{agent_id}:last_clear"
    try:
        if redis_pool:
            last = await redis_pool.get(debounce_key)
            if last and time.time() - float(last) < 120:
                return  # debounce: too soon (2 min)
            await redis_pool.set(debounce_key, str(time.time()), ex=300)

        # Find prompt file
        prompts_dir = BASE_DIR / "prompts"
        prompt_path = _find_agent_prompt(prompts_dir, agent_id)
        if not prompt_path:
            print(f"[clear] No prompt file found for agent {agent_id}")
            return

        session = f"{MA_PREFIX}-agent-{agent_id}"
        pane = f"{session}:0.0"

        # Step 1: Rotate events + log clear
        _rotate_events(agent_id)
        _log_event(agent_id, "clear", "auto /clear triggered")

        # Step 2: Send /clear
        await _run_subprocess(["tmux", "send-keys", "-t", pane, "/clear"], text=True, timeout=5)
        await asyncio.sleep(0.3)
        await _run_subprocess(["tmux", "send-keys", "-t", pane, "C-m"], text=True, timeout=5)
        print(f"[clear] Sent /clear to {agent_id}")

        # Step 3: Wait for Claude to be ready
        await asyncio.sleep(3)

        # Step 4: Send deviens agent
        cmd = f"deviens agent {prompt_path}"
        await _run_subprocess(["tmux", "send-keys", "-t", pane, cmd], text=True, timeout=5)
        await asyncio.sleep(0.3)
        result = await _run_subprocess(["tmux", "send-keys", "-t", pane, "C-m"], text=True, timeout=5)
        if result.returncode == 0:
            _log_event(agent_id, "deviens_agent", prompt_path.name)
            print(f"[clear] Sent /clear + 'deviens agent' to {agent_id} ({prompt_path.name})")
        else:
            print(f"[clear] Failed tmux send-keys for {agent_id}: {result.stderr}")
    except Exception as e:
        print(f"[clear] Error for {agent_id}: {e}")


async def _trigger_prompt_reload(agent_id: str):
    """Send 'deviens agent' via tmux send-keys after compacting (1x, debounced 60s)."""
    debounce_key = f"{MA_PREFIX}:agent:{agent_id}:last_reload"
    try:
        if redis_pool:
            last = await redis_pool.get(debounce_key)
            if last and time.time() - float(last) < 60:
                return  # debounce: too soon
            await redis_pool.set(debounce_key, str(time.time()), ex=120)

        # Find prompt file for this agent
        prompts_dir = BASE_DIR / "prompts"
        prompt_path = _find_agent_prompt(prompts_dir, agent_id)
        if not prompt_path:
            print(f"[reload] No prompt file found for agent {agent_id}")
            return
        session = f"{MA_PREFIX}-agent-{agent_id}"
        cmd = f"deviens agent {prompt_path}"

        # Send text then C-m (Enter) separately to avoid lost keystrokes
        await _run_subprocess(
            ["tmux", "send-keys", "-t", f"{session}:0.0", cmd],
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
    except Exception as e:
        print(f"[reload] Error for {agent_id}: {e}")


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
    if not redis_pool or not agents_data:
        return {}

    overrides = {}

    try:
        # Step 1: GET reload_sent flags for ALL agents (single pipeline)
        pipe = redis_pool.pipeline()
        for aid, _ in agents_data:
            pipe.get(f"{MA_PREFIX}:agent:{aid}:reload_sent")
        reload_flags = await pipe.execute()

        # Step 2a: Detect transitions → log events
        for aid, state in agents_data:
            prev = _prev_agent_states.get(aid, {})
            # compacting False→True
            if state.get('compacted') and not prev.get('compacted'):
                _log_event(aid, "compacting", "started")
            # api_error False→True
            if state.get('api_error') and not prev.get('api_error'):
                _log_event(aid, "api_error", "3+ API errors")
            # context_limit False→True
            if state.get('context_limit') and not prev.get('context_limit'):
                _log_event(aid, "context_limit", "reached")
            # model_change detected
            if state.get('model_change') and not prev.get('model_change'):
                _log_event(aid, "model", "/model detected in output")
            _prev_agent_states[aid] = dict(state)

        # Step 2b: Classify agents + set compacting timestamp flag
        now = time.time()
        for i, (aid, state) in enumerate(agents_data):
            ctx = state.get('context_pct', -1)
            is_compacting = state.get('compacted', False)
            done_compacting = state.get('done_compacting', False)
            context_limit = state.get('context_limit', False)
            api_error = state.get('api_error', False)
            flag_ts = float(reload_flags[i]) if reload_flags[i] else 0

            if ctx >= 0 or is_compacting or done_compacting or context_limit or api_error:
                elapsed = int(now - flag_ts) if flag_ts else 0
                print(f"[context] Agent {aid}: ctx={ctx}% compacting={is_compacting} done={done_compacting} limit={context_limit} api_err={api_error} flag={elapsed}s")

            # Context limit reached OR repeated API errors — agent is STUCK, immediate /clear + reload
            if context_limit or api_error:
                overrides[aid] = "needs_clear"
                asyncio.ensure_future(_trigger_context_clear(aid))
                continue

            if is_compacting and not done_compacting:
                # Red: compacting in progress
                overrides[aid] = "context_compacted"
                if not flag_ts:
                    # Set timestamp flag (when compacting started)
                    await redis_pool.set(f"{MA_PREFIX}:agent:{aid}:reload_sent", str(now), ex=600)
            elif ctx == 0 and not done_compacting:
                # Red: context at 0%, compacting imminent — also set flag
                overrides[aid] = "context_compacted"
                if not flag_ts:
                    await redis_pool.set(f"{MA_PREFIX}:agent:{aid}:reload_sent", str(now), ex=600)
            elif done_compacting:
                # "Conversation compacted" visible → compacting finished
                if state.get('has_bashes'):
                    overrides[aid] = "has_bashes"
                elif state.get('busy'):
                    overrides[aid] = "busy"
                # else: no override (idle)
            elif state.get('waiting_approval'):
                overrides[aid] = "waiting_approval"  # blue — interactive prompt (Enter to select)
            elif state.get('plan_mode'):
                overrides[aid] = "plan_mode"
            elif state.get('has_bashes'):
                overrides[aid] = "has_bashes"
            elif state.get('busy'):
                overrides[aid] = "busy"
            elif 1 <= ctx <= 10:
                overrides[aid] = "context_warning"

        # Step 3: After compacting finished, verify prompt retention
        # Conditions: flag exists + not compacting anymore + ctx != 0 (context refreshed) + waited >= 80s
        clear_ids = []
        for i, (aid, state) in enumerate(agents_data):
            flag_ts = float(reload_flags[i]) if reload_flags[i] else 0
            if not flag_ts:
                continue
            ctx = state.get('context_pct', -1)
            is_compacting = state.get('compacted', False)
            prompt_loaded = state.get('prompt_loaded', False)
            elapsed = now - flag_ts

            # Still compacting or at ctx=0 waiting → skip
            if is_compacting or ctx == 0:
                continue
            # Not enough time elapsed → skip (compacting takes ~90-120s)
            if elapsed < COMPACTING_WAIT_SECS:
                continue

            # Compacting is done (flag set, not compacting, ctx refreshed, waited enough)
            if prompt_loaded:
                clear_ids.append(aid)
                print(f"[reload] Agent {aid}: prompt in output after compacting ({int(elapsed)}s), no reload needed")
            else:
                # Deep capture (100 lines) to check further back
                session = f"{MA_PREFIX}-agent-{aid}"
                deep = await _run_subprocess(
                    ["tmux", "capture-pane", "-t", f"{session}:0.0", "-p", "-J", "-S", "-100"],
                    text=True, timeout=5
                )
                deep_text = deep.stdout if deep and deep.stdout else ""
                # Check for prompt path in deep capture: both flat (prompts/345-) and x45 (prompts/345/345)
                parent_aid = aid.split('-')[0] if '-' in aid else aid
                if f"prompts/{parent_aid}/{aid}" in deep_text or f"prompts/{aid}-" in deep_text:
                    clear_ids.append(aid)
                    print(f"[reload] Agent {aid}: prompt in deep capture ({int(elapsed)}s), no reload needed")
                else:
                    print(f"[reload] Agent {aid}: prompt NOT found ({int(elapsed)}s), sending deviens agent")
                    asyncio.ensure_future(_trigger_prompt_reload(aid))
                    clear_ids.append(aid)

        if clear_ids:
            pipe = redis_pool.pipeline()
            for aid in clear_ids:
                pipe.delete(f"{MA_PREFIX}:agent:{aid}:reload_sent")
            await pipe.execute()

    except Exception as e:
        print(f"[cache] batch status resolve error: {e}")

    return overrides


@app.get("/api/file")
async def read_prompt_file(path: str = "", reverse: bool = False):
    """Read a prompt file (only from prompts/ directory).
    Resolves named directories: prompts/345/file → prompts/345-name/file.
    reverse=true returns lines in reverse order (newest first for LOGS.md).
    """
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    full = (BASE_DIR / path).resolve()
    prompts_root = (BASE_DIR / "prompts").resolve()
    if not str(full).startswith(str(prompts_root)):
        raise HTTPException(status_code=403, detail="forbidden")
    # If not found, try resolving named directory (345 → 345-develop-fonction-beta)
    if not full.exists():
        parts = Path(path).parts  # e.g. ('prompts', '345', '345-system.md')
        if len(parts) >= 2 and parts[0] == 'prompts' and re.match(r'^\d{3}$', parts[1]):
            resolved_dir = _resolve_prompts_dir(BASE_DIR / "prompts", parts[1])
            if resolved_dir:
                full = (resolved_dir / Path(*parts[2:])).resolve()
                if not str(full).startswith(str(prompts_root)):
                    raise HTTPException(status_code=403, detail="forbidden")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="not found")
    try:
        content = full.read_text(encoding="utf-8")
        if reverse:
            lines = content.splitlines()
            content = "\n".join(reversed(lines))
    except Exception:
        raise HTTPException(status_code=500, detail="read error")
    return {"path": path, "content": content}


@app.get("/api/agents")
async def list_agents():
    """List all agents — reads from background cache (instant)"""
    agents = _cache["agents"]
    result = {
        "agents": agents,
        "count": len(agents),
        "timestamp": _cache["timestamp"],
    }
    if _cache.get("mode"):
        result["mode"] = _cache["mode"]
    if _cache.get("triangles"):
        result["triangles"] = _cache["triangles"]
    if _cache.get("agent_names"):
        result["agent_names"] = _cache["agent_names"]
    return result


@app.get("/api/agent/{agent_id}")
async def get_agent(agent_id: str):
    """Get single agent details"""
    if not redis_pool:
        raise HTTPException(status_code=503, detail="Redis not available")

    key = f"{MA_PREFIX}:agent:{agent_id}"
    data = await redis_pool.hgetall(key)

    if not data:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    return AgentStatus(
        id=agent_id,
        status=data.get("status", "unknown"),
        last_seen=int(data.get("last_seen", 0)),
        queue_size=int(data.get("queue_size", 0)),
        tasks_completed=int(data.get("tasks_completed", 0)),
        mode=data.get("mode", "unknown")
    ).model_dump()


@app.get("/api/config/logins-models")
async def get_logins_models():
    """Return available logins, models, defaults, and per-agent assignments."""
    prompts_dir = BASE_DIR / "prompts"

    # Collect non-symlink .login and .model files
    logins = sorted(
        f.stem for f in prompts_dir.glob("*.login")
        if not f.is_symlink() and f.stem != "default"
    )
    models = sorted(
        f.stem for f in prompts_dir.glob("*.model")
        if not f.is_symlink() and f.stem != "default"
    )

    # Resolve default symlinks
    default_login = ""
    dl = prompts_dir / "default.login"
    if dl.is_symlink():
        target = os.readlink(dl)
        default_login = Path(target).stem  # "claude1a.login" -> "claude1a"
    elif dl.exists():
        default_login = logins[0] if logins else ""

    default_model = ""
    dm = prompts_dir / "default.model"
    if dm.is_symlink():
        target = os.readlink(dm)
        default_model = Path(target).stem
    elif dm.exists():
        default_model = models[0] if models else ""

    # Gather agent IDs from cache + x45 detection
    agent_ids = set()
    for a in _cache.get("agents", []):
        agent_ids.add(a["id"])
    # Also scan prompts/ for numbered files/dirs that might not be running
    for f in prompts_dir.iterdir():
        m = re.match(r'^(\d{3})', f.name)
        if m:
            agent_ids.add(m.group(1))

    # Build per-agent config
    agents = []
    for aid in sorted(agent_ids, key=lambda x: tuple(int(p) for p in x.split("-"))):
        login_file = prompts_dir / f"{aid}.login"
        model_file = prompts_dir / f"{aid}.model"

        if login_file.is_symlink():
            agent_login = Path(os.readlink(login_file)).stem
            login_source = "override"
        else:
            agent_login = default_login
            login_source = "default"

        if model_file.is_symlink():
            agent_model = Path(os.readlink(model_file)).stem
            model_source = "override"
        else:
            agent_model = default_model
            model_source = "default"

        agents.append({
            "id": aid,
            "login": agent_login,
            "login_source": login_source,
            "model": agent_model,
            "model_source": model_source,
        })

    return {
        "logins": logins,
        "models": models,
        "default_login": default_login,
        "default_model": default_model,
        "agents": agents,
    }


@app.post("/api/config/logins-models")
async def update_login_model(data: LoginModelUpdate):
    """Create or remove a login/model symlink override for an agent."""
    prompts_dir = BASE_DIR / "prompts"

    if data.type not in ("login", "model"):
        raise HTTPException(status_code=400, detail="type must be 'login' or 'model'")

    # Validate agent_id format
    if data.agent_id != "default" and not re.match(r'^\d{3}(-\d{3})?$', data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    link_path = prompts_dir / f"{data.agent_id}.{data.type}"

    if data.value == "":
        # Remove override (only for non-default)
        if data.agent_id == "default":
            raise HTTPException(status_code=400, detail="cannot remove default")
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        return {"status": "removed", "agent_id": data.agent_id, "type": data.type}

    # Validate target exists
    target_file = prompts_dir / f"{data.value}.{data.type}"
    if not target_file.exists() or target_file.is_symlink():
        raise HTTPException(status_code=400, detail=f"target {data.value}.{data.type} not found")

    # Create/replace symlink
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(f"{data.value}.{data.type}")

    return {"status": "updated", "agent_id": data.agent_id, "type": data.type, "value": data.value}


@app.get("/api/config/tmux-width")
async def get_tmux_width():
    """Get current tmux window width from first agent session."""
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{window_width}"],
            text=True, capture_output=True, timeout=5
        )
        widths = [int(w) for w in result.stdout.strip().split('\n') if w.strip().isdigit()]
        return {"width": widths[0] if widths else 80}
    except Exception:
        return {"width": 80}


@app.post("/api/config/tmux-width")
async def set_tmux_width(data: dict):
    """Resize all tmux windows to the given width."""
    width = data.get("width")
    if not isinstance(width, int) or width < 80 or width > 400:
        raise HTTPException(status_code=400, detail="width must be 80-400")
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            text=True, capture_output=True, timeout=5
        )
        sessions = [s.strip() for s in result.stdout.strip().split('\n') if s.strip()]
        resized = 0
        for s in sessions:
            await _run_subprocess(
                ["tmux", "resize-window", "-t", s, "-x", str(width), "-y", "50"],
                text=True, capture_output=True, timeout=5
            )
            resized += 1
        return {"status": "ok", "width": width, "sessions": resized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/{agent_id}/restart")
async def restart_agent(agent_id: str):
    """Restart an agent via ./scripts/agent.sh restart <id>."""
    if not re.match(r'^\d{3}(-\d{3})?$', agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    script = BASE_DIR / "scripts" / "agent.sh"
    if not script.exists():
        raise HTTPException(status_code=500, detail="agent.sh not found")

    try:
        result = await _run_subprocess(
            ["bash", str(script), "restart", agent_id],
            text=True, timeout=60
        )
        output = result.stdout.strip()
        print(f"[restart] agent {agent_id}: {output}")

        return {
            "status": "restarted",
            "agent_id": agent_id,
            "output": output,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"restart failed: {e}")


@app.get("/api/agent/{agent_id}/events")
async def get_agent_events(agent_id: str, all: int = 0):
    """Get event log for an agent. ?all=1 includes archived (rotated) files."""
    d = _events_dir(agent_id)

    def _read_jsonl(path: Path) -> list:
        if not path.exists():
            return []
        lines = []
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return lines

    events = _read_jsonl(d / "events.jsonl")

    if all:
        archived = []
        for f in sorted(d.glob("events.*.jsonl")):
            archived.extend(_read_jsonl(f))
        return {"agent_id": agent_id, "events": events, "archived": archived}

    return {"agent_id": agent_id, "events": events}


class UpdateInput(BaseModel):
    text: str
    previous: str = ""
    submit: bool = False


class SendKeys(BaseModel):
    keys: list[str]  # tmux key names: "Enter", "C-c", "Escape", etc.


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub('', text)


def _extract_current_input(ansi_output: str) -> str:
    """Extract typed input from tmux output captured with -e (ANSI codes).

    Distinguishes real typed text from Claude Code suggestions:
    - Suggestion: \\x1b[7m (reverse video = cursor) appears at position 0
      before any normal text. The cursor sitting at the start means nothing
      was typed, everything is ghost/suggestion text. Returns "".
    - Typed text: normal characters appear before any \\x1b[7m cursor.
      Returns only the typed portion (before suggestion/cursor escapes).

    Only searches the last 8 non-empty lines to avoid false prompt matches.
    """
    SKIP_MARKERS = ["⏵", "───"]

    lines = ansi_output.rstrip().split("\n")
    checked = 0

    for line in reversed(lines):
        clean = _strip_ansi(line).strip()
        if not clean:
            continue
        if any(m in clean for m in SKIP_MARKERS) or clean.startswith("⏺"):
            continue

        checked += 1
        if checked > 8:
            break

        # Look for ❯ prompt (with or without ANSI around it)
        prompt_match = re.search(r'❯[\xa0 ]', line)
        if prompt_match:
            after = line[prompt_match.end():]

            # Check if \x1b[7m (cursor/reverse video) appears before any normal text.
            # Pattern: optional ANSI codes, then \x1b[7m → cursor at pos 0 → all suggestion
            if re.match(r'(?:\x1b\[[0-9;]*m)*\x1b\[7m', after):
                return ""

            # Real text exists before cursor. Extract up to first suggestion marker:
            # \x1b[7m (cursor), \x1b[2m (dim), \x1b[0;2m (reset+dim)
            sugg_start = re.search(r'\x1b\[(?:7m|2m|0;2m)', after)
            if sugg_start:
                typed_part = after[:sugg_start.start()]
            else:
                typed_part = after

            return _strip_ansi(typed_part).strip()

        # Fallback: other prompt types (no suggestion detection)
        for prompt in ["$ ", ">>> ", "... ", "> "]:
            if prompt in clean:
                idx = clean.rfind(prompt)
                return clean[idx + len(prompt):]

    return ""


@app.post("/api/agent/{agent_id}/send")
async def send_to_agent(agent_id: str, msg: SendMessage):
    """Send message to an agent via tmux send-keys (with Enter)"""
    session_name = f"{MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        # Check if session exists
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Send message via tmux send-keys
        await _run_subprocess(
            ["tmux", "send-keys", "-t", target, msg.message, "Enter"], check=True
        )

        return {
            "status": "sent",
            "agent_id": agent_id,
            "message_length": len(msg.message),
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to send: {str(e)}")


@app.post("/api/agent/{agent_id}/input")
async def update_agent_input(agent_id: str, data: UpdateInput):
    """Update the current input line in tmux (co-editing)"""
    session_name = f"{MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        # Check if session exists
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Incremental diff: only send backspaces + new chars
        prev = data.previous or ""
        new = data.text or ""

        # Find common prefix
        i = 0
        while i < len(prev) and i < len(new) and prev[i] == new[i]:
            i += 1

        # Backspace to remove divergent old chars
        bs = len(prev) - i
        if bs > 0:
            await _run_subprocess(
                ["tmux", "send-keys", "-t", target] + ["BSpace"] * bs, check=True
            )

        # Type new chars
        new_chars = new[i:]
        if new_chars:
            await _run_subprocess(
                ["tmux", "send-keys", "-t", target, "-l", new_chars], check=True
            )

        # Submit if requested
        if data.submit:
            await _run_subprocess(
                ["tmux", "send-keys", "-t", target, "Enter"], check=True
            )

        return {
            "status": "updated",
            "agent_id": agent_id,
            "text": data.text,
            "submitted": data.submit,
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update input: {str(e)}")


ALLOWED_KEYS = {"Enter", "C-c", "Escape", "C-u", "C-d", "C-l", "C-z", "Up", "Down", "Tab", "Space", "y", "n"}


@app.post("/api/agent/{agent_id}/keys")
async def send_keys_to_agent(agent_id: str, data: SendKeys):
    """Send raw tmux keys to an agent (Enter, Ctrl+C, Escape, etc.)"""
    session_name = f"{MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        for key in data.keys:
            if key not in ALLOWED_KEYS:
                raise HTTPException(status_code=400, detail=f"Key not allowed: {key}")
            await _run_subprocess(
                ["tmux", "send-keys", "-t", target, key], check=True
            )

        return {
            "status": "sent",
            "agent_id": agent_id,
            "keys": data.keys,
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to send keys: {str(e)}")


@app.get("/api/agent/{agent_id}/output")
async def get_agent_output(agent_id: str, lines: int = 500):
    """Capture tmux pane output for an agent"""
    session_name = f"{MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        # Check if session exists
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Capture pane content (plain for display)
        result = await _run_subprocess(
            ["tmux", "capture-pane", "-t", target, "-p", "-J", "-S", f"-{lines}"], text=True
        )
        output = result.stdout.rstrip('\n ')

        # Capture with ANSI codes for input detection (suggestion vs typed)
        result_ansi = await _run_subprocess(
            ["tmux", "capture-pane", "-t", target, "-p", "-e", "-S", "-20"], text=True
        )
        current_input = _extract_current_input(result_ansi.stdout)

        return {
            "agent_id": agent_id,
            "output": output,
            "current_input": current_input,
            "lines": lines,
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to capture: {str(e)}")


# === Keycloak Proxy ===

@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_keycloak(request: Request, path: str):
    """Auth endpoint: proxy to Keycloak. Returns 503 if Keycloak is unavailable."""

    url = f"{KEYCLOAK_URL}/{path}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host"]}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=request.method, url=url, headers=headers, content=body,
                params=request.query_params, timeout=30.0
            )
            return Response(content=response.content, status_code=response.status_code,
                            headers=dict(response.headers))
        except Exception as e:
            return Response(
                content=json.dumps({"error": "service_unavailable", "error_description": "Keycloak is not reachable. Start Keycloak first."}),
                status_code=503,
                headers={"Content-Type": "application/json"},
            )


# === WebSocket ===

class ConnectionManager:
    """Manage WebSocket connections"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


@app.websocket("/ws/agent/{agent_id}")
async def websocket_agent_output(websocket: WebSocket, agent_id: str):
    """WebSocket endpoint for real-time agent tmux output with input sync"""
    await websocket.accept()

    # Poll interval from query param (default 1.0s)
    poll = float(websocket.query_params.get("poll", "2.0"))
    poll = max(0.5, min(poll, 10.0))  # Clamp 0.5-10s

    session_name = f"{MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"
    last_output = ""
    last_input = ""

    try:
        while True:
            # Capture pane content (plain for display)
            result = await _run_subprocess(
                ["tmux", "capture-pane", "-t", target, "-p", "-J", "-S", "-500"], text=True
            )

            if result.returncode != 0:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Agent {agent_id} session not found"
                })
                break

            current_output = result.stdout.rstrip('\n ')

            # Capture with ANSI for input detection (suggestion vs typed)
            result_ansi = await _run_subprocess(
                ["tmux", "capture-pane", "-t", target, "-p", "-e", "-S", "-20"], text=True
            )
            current_input = _extract_current_input(result_ansi.stdout)

            # Send output if changed
            if current_output != last_output:
                await websocket.send_json({
                    "type": "output",
                    "agent_id": agent_id,
                    "output": current_output,
                    "timestamp": int(time.time())
                })
                last_output = current_output

            # Send input if changed (separate message for input sync)
            if current_input != last_input:
                await websocket.send_json({
                    "type": "input_sync",
                    "agent_id": agent_id,
                    "current_input": current_input,
                    "timestamp": int(time.time())
                })
                last_input = current_input

            await asyncio.sleep(poll)

    except Exception:
        # Any disconnect (WebSocketDisconnect, ConnectionResetError,
        # IncompleteReadError, ConnectionClosedError, ClientDisconnected)
        # is normal — the client or proxy closed the connection.
        pass


@app.websocket("/ws/messages")
async def websocket_messages(websocket: WebSocket):
    """WebSocket endpoint for real-time agent messages"""
    await manager.connect(websocket)

    try:
        # Track last seen message IDs per stream
        last_ids = {}

        while True:
            if not redis_pool:
                await asyncio.sleep(1)
                continue

            # Get all agent outbox streams
            cursor = 0
            streams = {}
            while True:
                cursor, keys = await redis_pool.scan(cursor, match=f"{MA_PREFIX}:agent:*:outbox", count=100)
                for key in keys:
                    stream_id = last_ids.get(key, "$")
                    streams[key] = stream_id
                if cursor == 0:
                    break

            if not streams:
                await asyncio.sleep(0.5)
                continue

            # Read from all streams
            try:
                result = await redis_pool.xread(streams, block=1000, count=10)

                for stream_name, messages in result:
                    for msg_id, data in messages:
                        last_ids[stream_name] = msg_id

                        # Extract agent ID from stream name
                        parts = stream_name.split(":")
                        agent_id = parts[2] if len(parts) >= 3 else "unknown"

                        await manager.broadcast({
                            "type": "message",
                            "agent_id": agent_id,
                            "msg_id": msg_id,
                            "data": data,
                            "timestamp": int(time.time())
                        })
            except Exception as e:
                print(f"WebSocket stream error: {e}")
                await asyncio.sleep(0.5)

    except Exception:
        manager.disconnect(websocket)


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for agent status updates — reads from background cache"""
    await websocket.accept()

    # Poll interval from query param (default 5s, min = cache interval)
    poll = float(websocket.query_params.get("poll", "5"))
    poll = max(CACHE_REFRESH_INTERVAL, min(poll, 60))  # Clamp to cache interval minimum

    last_sent = ""  # JSON string of last sent data to avoid sending duplicates

    try:
        while True:
            agents = _cache["agents"]
            payload = {
                "type": "status_update",
                "agents": [{"id": a["id"], "status": a["status"], "last_seen": a["last_seen"]} for a in agents],
                "timestamp": _cache["timestamp"],
            }
            if _cache.get("mode"):
                payload["mode"] = _cache["mode"]
            if _cache.get("triangles"):
                payload["triangles"] = _cache["triangles"]
            if _cache.get("agent_names"):
                payload["agent_names"] = _cache["agent_names"]
            payload_str = json.dumps(payload, sort_keys=True)

            # Only send if data changed
            if payload_str != last_sent:
                await websocket.send_json(payload)
                last_sent = payload_str

            await asyncio.sleep(poll)

    except Exception:
        pass


# === Static Files (Frontend) ===

# Serve static assets (JS, CSS, etc.)
frontend_path = os.path.join(os.path.dirname(__file__), FRONTEND_DIR)
if os.path.exists(frontend_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_path, "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        """Serve frontend index.html"""
        return FileResponse(os.path.join(frontend_path, "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Catch-all for SPA routing"""
        file_path = os.path.join(frontend_path, path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_path, "index.html"))


# === Main ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
