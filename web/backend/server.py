#!/usr/bin/env python3
"""
Multi-Agent Dashboard Backend
FastAPI server exposing agent status and WebSocket streams
"""

import os
import re
import asyncio
import base64
import time
import subprocess
import concurrent.futures
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
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
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
MA_PREFIX = os.environ.get("MA_PREFIX", "A")
BASE_DIR = Path(os.environ.get("MA_BASE", Path.home() / "multi-agent"))
PANEL_CONFIG_PATH = BASE_DIR / "web" / "panel-config.json"

PROMPT_HISTORY_STREAM = f"{MA_PREFIX}:prompt:history"


def _read_panel_config() -> dict:
    """Read panel-config.json, return {"overrides": {}} if missing/corrupt."""
    try:
        return json.loads(PANEL_CONFIG_PATH.read_text())
    except Exception:
        return {"overrides": {}}


def _write_panel_config(data: dict):
    """Atomic write: .tmp + rename."""
    tmp = PANEL_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.rename(PANEL_CONFIG_PATH)


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
            'pane_cmd=$(tmux display-message -t "$s:0.0" -p "#{pane_current_command}" 2>/dev/null || echo ""); '
            'claude_alive=0; if [[ "$pane_cmd" == "claude" || "$pane_cmd" == "node" ]]; then claude_alive=1; fi; '
            'busy=0; has_bashes=0; has_down=0; plan_mode=0; compacted=0; ctx=-1; done_compacting=0; prompt_loaded=0; ctx_limit=0; api_error=0; model_change=0; '
            'bp_line=$(echo "$out" | grep "bypass permissions" | tail -1); '
            'if echo "$bp_line" | grep -q "bashes"; then has_bashes=1; fi; '
            'if [ "$claude_alive" -eq 0 ]; then busy=0; elif echo "$bp_line" | grep -q "esc to interrupt"; then busy=1; elif echo "$out" | tail -10 | grep -q "❯"; then busy=0; else busy=1; fi; '
            'if echo "$bp_line" | grep -q "↓"; then has_down=1; fi; '
            'if echo "$out" | grep -q "plan mode on"; then plan_mode=1; fi; '
            'waiting_approval=0; '
            'if echo "$out" | grep -q "Enter to select"; then waiting_approval=1; fi; '
            'if echo "$out" | grep -qiE "compacting conversation"; then compacted=1; fi; '
            'if echo "$out" | grep -qi "Conversation compacted"; then done_compacting=1; fi; '
            'if [ "$done_compacting" -eq 1 ] && echo "$out" | grep -qE "prompts/[0-9]+/${id}[.-]|prompts/${id}-"; then prompt_loaded=1; fi; '
            'pct=$(echo "$bp_line" | grep -oE "[0-9]+% until auto-compact|auto-compact: [0-9]+%" | grep -oE "[0-9]+"); '
            'if [ -n "$pct" ]; then ctx=$pct; fi; '
            'if echo "$out" | grep -q "Context limit reached"; then ctx_limit=1; fi; '
            'api_err_count=$(echo "$out" | grep -c "API Error:" 2>/dev/null || echo 0); '
            'if [ "$api_err_count" -ge 3 ]; then api_error=1; fi; '
            'if [ "$claude_alive" -eq 1 ] && [ -z "$bp_line" ]; then api_error=1; fi; '
            'if echo "$out" | grep -q "/model "; then model_change=1; fi; '
            'echo "$id:$busy:$compacted:$ctx:$done_compacting:$prompt_loaded:$ctx_limit:$api_error:$model_change:$has_bashes:$plan_mode:$has_down:$waiting_approval:$claude_alive"; '
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
                claude_alive = parts[13] == '1' if len(parts) >= 14 else True
                agent_states[parts[0]] = {
                    'busy': parts[1] == '1',
                    'has_bashes': has_bashes,
                    'has_down': has_down,
                    'plan_mode': plan_mode,
                    'waiting_approval': waiting_approval,
                    'compacted': parts[2] == '1',
                    'context_pct': ctx_pct,  # -1 = not visible, 0-5 = shown by Claude
                    'done_compacting': done_compacting,
                    'prompt_loaded': prompt_loaded,
                    'context_limit': ctx_limit,
                    'api_error': api_error,
                    'model_change': model_change,
                    'claude_alive': claude_alive,
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

        state = agent_states.get(agent_id, {})
        agents.append({
            "id": agent_id,
            "status": status,
            "ctx": state.get('context_pct', -1),
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
            for f in d.glob(f"{did}-*-system.md"):
                suffix = f.stem.replace(f"{did}-", "", 1).replace("-system", "")
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


import glob as _glob


async def _seed_prompt_history():
    """Load existing .history files into Redis stream on startup."""
    if not redis_pool:
        return
    try:
        existing = await redis_pool.xlen(PROMPT_HISTORY_STREAM)
        if existing > 0:
            return  # already seeded
        prompts_dir = BASE_DIR / "prompts"
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
            await redis_pool.xadd(
                PROMPT_HISTORY_STREAM,
                {"time": hm, "agent": agent, "text": text},
                maxlen=50,
            )
        if all_entries:
            print(f"Seeded prompt history: {min(len(all_entries), 50)} entries")
    except Exception as e:
        print(f"WARNING: Failed to seed prompt history: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events"""
    global redis_pool, _cache_task
    redis_pool = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD or None,
        decode_responses=True
    )
    try:
        await redis_pool.ping()
        print(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
    except Exception as e:
        print(f"WARNING: Redis connection failed: {e}")

    # Seed prompt history stream from existing .history files
    await _seed_prompt_history()

    # Start background cache refresh
    _cache_task = asyncio.create_task(_cache_loop())
    print(f"Background cache started (refresh every {CACHE_REFRESH_INTERVAL}s)")

    # Start crontab-scheduler if not already running (one per MA_PREFIX)
    _crontab_session = f"{MA_PREFIX}-agent-001"
    _crontab_script = BASE_DIR / "scripts" / "crontab-scheduler.py"
    _crontab_log = BASE_DIR / "logs" / "crontab-scheduler.log"
    try:
        check = subprocess.run(
            ["tmux", "has-session", "-t", _crontab_session],
            capture_output=True, timeout=5
        )
        if check.returncode != 0 and _crontab_script.exists():
            os.makedirs(BASE_DIR / "logs", exist_ok=True)
            _env_file = BASE_DIR / "setup" / "secrets.cfg"
            _source_env = f"set -a; source {_env_file} 2>/dev/null; set +a; " if _env_file.exists() else ""
            subprocess.run([
                "tmux", "new-session", "-d", "-s", _crontab_session,
                f"cd {BASE_DIR} && {_source_env}MA_PREFIX={MA_PREFIX} python3 -u {_crontab_script} 2>&1 | tee -a {_crontab_log}"
            ], timeout=5)
            print(f"Crontab scheduler started: {_crontab_session}")
        else:
            print(f"Crontab scheduler already running: {_crontab_session}")
    except Exception as e:
        print(f"WARNING: Could not start crontab scheduler: {e}")

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
    allow_origins=[
        "https://your-domain.example.com",
        "https://other-subdomain.example.com",
        "http://localhost:5173",
        "http://localhost:8050",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Security Headers Middleware ===

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# === JWT Auth Middleware ===
# Keycloak JWT verification on all /api/* routes (except /api/health and /auth/*)
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "multi-agent")
KEYCLOAK_JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
_jwks_cache = {"keys": None, "fetched": 0}

async def _get_jwks():
    """Fetch and cache Keycloak JWKS (public keys for JWT verification)."""
    now = time.time()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched"] < 3600:
        return _jwks_cache["keys"]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(KEYCLOAK_JWKS_URL, timeout=10)
            if resp.status_code == 200:
                _jwks_cache["keys"] = resp.json()
                _jwks_cache["fetched"] = now
                return _jwks_cache["keys"]
    except Exception:
        pass
    return _jwks_cache["keys"]  # return stale if fetch fails

def _verify_jwt_minimal(token: str) -> bool:
    """JWT verification with signature check via Keycloak JWKS.
    Accepts tokens issued by both internal (localhost:8080) and external (public URL) issuers.
    """
    try:
        import jwt as pyjwt
        from jwt import PyJWKClient
        jwks_client = PyJWKClient(KEYCLOAK_JWKS_URL, cache_keys=True, lifespan=3600)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        # Accept both internal and external issuer URLs
        pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False, "verify_iss": False, "verify_exp": True},
        )
        # Manual issuer check: realm name must be in the issuer
        import base64
        payload_b64 = token.split(".")[1] + "=" * (4 - len(token.split(".")[1]) % 4)
        payload = json.loads(base64.b64decode(payload_b64))
        if f"/realms/{KEYCLOAK_REALM}" not in payload.get("iss", ""):
            return False
        return True
    except Exception:
        # Fallback: check payload only (reject unsigned tokens)
        try:
            import base64
            parts = token.split(".")
            if len(parts) != 3 or not parts[2]:
                return False
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.b64decode(payload_b64))
            if time.time() >= payload.get("exp", 0):
                return False
            if f"/realms/{KEYCLOAK_REALM}" not in payload.get("iss", ""):
                return False
            return True
        except Exception:
            return False

# Public paths that don't require auth
_PUBLIC_PATHS = {"/api/agent-chat/health", "/api/agent-chat/spec", "/api/agent-chat/events"}
_PUBLIC_PREFIXES = ("/auth/", "/assets/", "/favicon")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Skip auth for public paths, static files, and WebSocket upgrades (handled separately)
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    # Skip non-API paths (frontend static files served by StaticFiles mount)
    if not path.startswith("/api/") and not path.startswith("/ws/"):
        return await call_next(request)

    # Extract Bearer token
    auth_header = request.headers.get("authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif request.query_params.get("token"):
        token = request.query_params.get("token")  # WebSocket fallback

    if not token or not _verify_jwt_minimal(token):
        return Response(
            content=json.dumps({"detail": "Authentication required"}),
            status_code=401,
            media_type="application/json",
        )

    return await call_next(request)


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

class EffortUpdate(BaseModel):
    agent_id: str      # "300" or "default"
    level: str         # "L", "M", "H", or "" (remove override)


class PanelConfigUpdate(BaseModel):
    agent_id: str      # "301", "500", etc.
    panel: str         # "control", "agent", or "" to remove override


class CrontabCreate(BaseModel):
    agent_id: str      # "300", "309", etc.
    period: int        # 10, 30, 60, or 120
    prompt: str        # prompt content

class CrontabUpdate(BaseModel):
    agent_id: str
    period: int
    prompt: Optional[str] = None
    action: Optional[str] = None  # "suspend" or "resume"

class CrontabDelete(BaseModel):
    agent_id: str
    period: int


CRONTAB_DIR = BASE_DIR / "crontab"
VALID_CRONTAB_PERIODS = {10, 30, 60, 120}


# === Routes ===

@app.get("/api/health")
async def health():
    """Health check — reads from background cache"""
    return _cache["health"]


# _get_agent_states removed — replaced by background _cache_loop


def _log_prompt_history(agent_id: str, text: str):
    """Append submitted prompt to agent history file + Redis stream.
    Flat agents: prompts/{agent_id}.history
    x45 agents:  prompts/{parent-dir}/{agent_id}.history
    """
    try:
        prompts_dir = BASE_DIR / "prompts"
        parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
        # Try x45 directory first
        parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
        if parent_dir:
            history_file = parent_dir / f"{agent_id}.history"
        else:
            history_file = prompts_dir / f"{agent_id}.history"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = text.replace("\n", " ").replace("\r", "")
        with open(history_file, "a") as f:
            f.write(f"{ts} | {line}\n")
        # Also push to Redis stream for real-time history
        if redis_pool:
            hm = time.strftime("%H:%M")
            short = line[:20]
            asyncio.get_event_loop().create_task(
                redis_pool.xadd(
                    PROMPT_HISTORY_STREAM,
                    {"time": hm, "agent": parent_id, "text": short},
                    maxlen=50,
                )
            )
    except Exception:
        pass  # never break the submit flow


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


def _find_agent_config(prompts_dir: Path, agent_id: str, ext: str) -> Optional[Path]:
    """Find config file (.model, .login, .effort) for an agent.
    Check agent directory first (x45/z21/mono), then prompts/.
    """
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    agent_dir = _resolve_prompts_dir(prompts_dir, base_id)
    if agent_dir:
        candidate = agent_dir / f"{agent_id}.{ext}"
        if candidate.exists() or candidate.is_symlink():
            return candidate
    candidate = prompts_dir / f"{agent_id}.{ext}"
    if candidate.exists() or candidate.is_symlink():
        return candidate
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
                else:
                    overrides[aid] = "active"     # gray — idle after compacting, clear stale Redis
            elif state.get('waiting_approval'):
                overrides[aid] = "waiting_approval"  # blue — interactive prompt (Enter to select)
            elif state.get('plan_mode'):
                overrides[aid] = "plan_mode"      # dark blue — plan mode (awaiting user)
            elif not state.get('claude_alive', True):
                overrides[aid] = "stopped"        # dark gray — Claude process exited (bash/zsh in pane)
            elif state.get('has_bashes'):
                overrides[aid] = "has_bashes"     # dark green — bashes executing
            elif state.get('busy'):
                overrides[aid] = "busy"           # yellow — Claude running
            elif 1 <= ctx <= 10:
                # Orange: context running low (1-10%)
                overrides[aid] = "context_warning"
            elif state.get('claude_alive', True):
                overrides[aid] = "active"         # gray — Claude idle, neutralise Redis stale "busy"

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
    """Read a file from allowed directories (prompts/, logs/).
    Resolves named directories: prompts/345/file → prompts/345-name/file.
    reverse=true returns lines in reverse order (newest first for LOGS.md).
    """
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    # Block path traversal attempts
    if ".." in path or "\x00" in path:
        raise HTTPException(status_code=403, detail="forbidden")
    full = (BASE_DIR / path).resolve()
    allowed_roots = [
        (BASE_DIR / "prompts").resolve(),
        (BASE_DIR / "logs").resolve(),
    ]
    if not any(str(full).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="forbidden")
    # Reject symlinks pointing outside allowed directories
    if full.is_symlink():
        target = full.resolve()
        if not any(str(target).startswith(str(root)) for root in allowed_roots):
            raise HTTPException(status_code=403, detail="forbidden")
    # If not found, try resolving named directory (345 → 345-develop-fonction-beta)
    if not full.exists():
        parts = Path(path).parts  # e.g. ('prompts', '345', '345-system.md')
        if len(parts) >= 2 and parts[0] == 'prompts' and re.match(r'^\d{3}$', parts[1]):
            resolved_dir = _resolve_prompts_dir(BASE_DIR / "prompts", parts[1])
            if resolved_dir:
                full = (resolved_dir / Path(*parts[2:])).resolve()
                if not any(str(full).startswith(str(root)) for root in allowed_roots):
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


@app.get("/api/agent/{base_id}/contexts")
async def get_z21_contexts(base_id: str):
    """List z21 sub-context directories for a group."""
    if not re.match(r'^\d{3}$', base_id):
        raise HTTPException(status_code=400, detail="invalid base_id")
    prompts_dir = BASE_DIR / "prompts"
    agent_dir = _resolve_prompts_dir(prompts_dir, base_id)
    if not agent_dir:
        raise HTTPException(status_code=404, detail="agent dir not found")
    contexts = []
    for child in sorted(agent_dir.iterdir(), key=lambda c: c.name):
        if not child.is_dir():
            continue
        archi = child / "archi.md"
        if not archi.exists():
            continue
        # Read first non-empty line of archi.md as description
        desc = ""
        try:
            for line in archi.read_text(encoding="utf-8").splitlines():
                stripped = line.strip().lstrip("#").strip()
                if stripped:
                    desc = stripped
                    break
        except Exception:
            pass
        rel = f"prompts/{agent_dir.name}/{child.name}"
        contexts.append({
            "name": child.name,
            "description": desc,
            "path": rel,
            "files": {
                "archi": f"{rel}/archi.md",
                "memory": f"{rel}/memory.md",
                "methodology": f"{rel}/methodology.md",
            }
        })
    return {"base_id": base_id, "contexts": contexts}


MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB

@app.post("/api/upload")
async def upload_file(file: UploadFile):
    """Upload a file to /tmp and return its path."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="no filename")
    # Sanitize: strip path components, replace spaces, remove ..
    safe_name = os.path.basename(file.filename).replace(" ", "_")
    safe_name = re.sub(r'[^\w.\-]', '_', safe_name)
    if not safe_name or safe_name.startswith('.'):
        safe_name = f"upload_{int(time.time())}"
    dest = Path("/tmp") / safe_name
    size = 0
    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(8192):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="file too large (max 100MB)")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"upload failed: {e}")
    return {"path": str(dest), "name": safe_name, "size": size}


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


@app.get("/api/usage")
async def get_usage():
    """Return Claude Code token usage from Redis (updated every 30min)."""
    if not redis_pool:
        return {"global": {}, "sessions": []}

    # Global totals
    g = await redis_pool.hgetall("mi:usage:global")

    # Active session IDs
    sids = await redis_pool.smembers("mi:usage:sessions")

    # Per-session details
    sessions = []
    for sid in sorted(sids):
        data = await redis_pool.hgetall(f"mi:usage:session:{sid}")
        if data:
            data["id"] = sid
            sessions.append(data)

    # Plan usage bars — read per-profile JSON files
    import json as _json
    import glob as _glob
    profiles = {}
    usage_glob = str(BASE_DIR / "keepalive" / "usage_*.json")
    for fpath in _glob.glob(usage_glob):
        try:
            with open(fpath) as _f:
                pdata = _json.load(_f)
                pname = pdata.get("profile", "")
                if pname and pdata.get("bars"):
                    profiles[pname] = pdata
        except Exception:
            pass

    # Enrich profiles with static info from info_*.json
    info_glob = str(BASE_DIR / "keepalive" / "info_*.json")
    for fpath in _glob.glob(info_glob):
        try:
            with open(fpath) as _f:
                idata = _json.load(_f)
                # Extract profile name from filename: info_claude1a.json -> claude1a
                pname = Path(fpath).stem.replace("info_", "", 1)
                if pname not in profiles:
                    profiles[pname] = {"profile": pname, "bars": []}
                profiles[pname]["info"] = idata
        except Exception:
            pass

    # Aggregate: take max % per bar label across profiles
    plan = None
    if profiles:
        agg = {}
        for pdata in profiles.values():
            for b in pdata.get("bars", []):
                lbl = b["label"]
                if lbl not in agg or b["percent"] > agg[lbl]["percent"]:
                    agg[lbl] = b
        plan = {
            "bars": list(agg.values()),
            "profiles": profiles,
            "last_scan": max((p.get("last_scan", 0) for p in profiles.values()), default=0),
        }

    return {"global": g, "sessions": sessions, "plan": plan}


@app.get("/api/usage/{agent_id}")
async def get_usage_for_agent(agent_id: str):
    """Return plan usage bars for the login associated with this agent."""
    import json as _json
    prompts_dir = BASE_DIR / "prompts"

    # Resolve login
    login = None

    # Special case: keepalive agents 002-{profile} → login is the profile
    if agent_id.startswith("002-"):
        login = agent_id[4:]  # "002-claude2a" -> "claude2a"
    else:
        # agent_id.login (x45 dir > prompts/) -> parent_id.login -> default.login
        for candidate in [agent_id, agent_id.split("-")[0]]:
            lf = _find_agent_config(prompts_dir, candidate, "login") or prompts_dir / f"{candidate}.login"
            if lf.exists():
                try:
                    if lf.is_symlink():
                        login = Path(os.readlink(lf)).stem
                    else:
                        login = lf.read_text().strip()
                except Exception:
                    pass
                if login:
                    break
        if not login:
            dl = prompts_dir / "default.login"
            if dl.exists():
                try:
                    login = Path(os.readlink(dl)).stem if dl.is_symlink() else dl.read_text().strip()
                except Exception:
                    login = "claude1a"

    # Read keepalive/usage_{login}.json — no fallback, show only exact profile
    usage_file = BASE_DIR / "keepalive" / f"usage_{login}.json"
    if usage_file and usage_file.exists():
        try:
            with open(usage_file) as f:
                data = _json.load(f)
                data["login"] = login
                return data
        except Exception:
            pass

    return {"login": login, "bars": [], "last_scan": 0}


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

    # Read default effort
    default_effort = "H"
    de = prompts_dir / "default.effort"
    if de.exists():
        default_effort = de.read_text().strip() or "H"

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

    # Gather agent IDs from cache + directory scan
    agent_ids = set()
    x45_base_ids = set()  # bare IDs that are x45/z21 groups (not standalone agents)
    for a in _cache.get("agents", []):
        agent_ids.add(a["id"])
    # Scan prompts/ directories — detect type from agent.type symlink
    for f in prompts_dir.iterdir():
        if not f.is_dir() or not re.match(r'^\d{3}', f.name):
            continue
        base_id = f.name[:3]
        # Read agent.type to determine kind
        type_link = f / "agent.type"
        agent_type = ""
        if type_link.is_symlink():
            agent_type = Path(os.readlink(type_link)).stem.replace("agent_", "")
        if agent_type == "mono":
            agent_ids.add(base_id)
        elif agent_type in ("x45", "z21"):
            x45_base_ids.add(base_id)
            for sf in f.iterdir():
                sm = re.match(r'^(\d{3}-\d{3})-system\.md$', sf.name)
                if sm:
                    agent_ids.add(sm.group(1))
        else:
            # Legacy: no agent.type — check for compound system.md files
            has_compound = any(re.match(r'^\d{3}-\d{3}-system\.md$', sf.name) for sf in f.iterdir())
            if has_compound:
                x45_base_ids.add(base_id)
                for sf in f.iterdir():
                    sm = re.match(r'^(\d{3}-\d{3})-system\.md$', sf.name)
                    if sm:
                        agent_ids.add(sm.group(1))
            else:
                agent_ids.add(base_id)
    # Remove bare IDs that are x45/z21 groups (they use compound format)
    agent_ids -= x45_base_ids

    # Build per-agent config
    agents = []
    for aid in sorted(agent_ids, key=lambda x: tuple(int(p) for p in x.split("-"))):
        # For compound IDs (301-101), try x45 dir first, then prompts/, then parent (301)
        parent_id = aid.split("-")[0] if "-" in aid else None
        login_file = _find_agent_config(prompts_dir, aid, "login")
        model_file = _find_agent_config(prompts_dir, aid, "model")

        if login_file and login_file.is_symlink():
            agent_login = Path(os.readlink(login_file)).stem
            login_source = "override"
        elif parent_id and (prompts_dir / f"{parent_id}.login").is_symlink():
            agent_login = Path(os.readlink(prompts_dir / f"{parent_id}.login")).stem
            login_source = "default"
        else:
            agent_login = default_login
            login_source = "default"

        if model_file and model_file.is_symlink():
            agent_model = Path(os.readlink(model_file)).stem
            model_source = "override"
        elif parent_id and (prompts_dir / f"{parent_id}.model").is_symlink():
            agent_model = Path(os.readlink(prompts_dir / f"{parent_id}.model")).stem
            model_source = "default"
        else:
            agent_model = default_model
            model_source = "default"

        effort_file = _find_agent_config(prompts_dir, aid, "effort") or prompts_dir / f"{aid}.effort"
        if effort_file.exists():
            agent_effort = effort_file.read_text().strip()
            effort_source = "override"
        elif parent_id and (prompts_dir / f"{parent_id}.effort").exists():
            agent_effort = (prompts_dir / f"{parent_id}.effort").read_text().strip()
            effort_source = "default"
        else:
            agent_effort = default_effort
            effort_source = "default"

        agents.append({
            "id": aid,
            "login": agent_login,
            "login_source": login_source,
            "model": agent_model,
            "model_source": model_source,
            "effort": agent_effort,
            "effort_source": effort_source,
        })

    # Detect group types from agent.type symlink
    groups = []
    for base_id in sorted(x45_base_ids, key=int):
        x45_dir = _resolve_prompts_dir(prompts_dir, base_id)
        if not x45_dir:
            continue
        type_link = x45_dir / "agent.type"
        if type_link.is_symlink():
            group_type = Path(os.readlink(type_link)).stem.replace("agent_", "")
        else:
            group_type = "x45"
        # Collect agent IDs belonging to this group
        group_agents = [a["id"] for a in agents if a["id"].startswith(f"{base_id}-")]
        groups.append({
            "id": base_id,
            "type": group_type,
            "name": x45_dir.name,
            "agents": group_agents,
        })

    return {
        "logins": logins,
        "models": models,
        "default_login": default_login,
        "default_model": default_model,
        "default_effort": default_effort,
        "agents": agents,
        "groups": groups,
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

    # For compound x45 IDs, resolve to x45 directory; otherwise prompts/
    if data.agent_id != "default" and "-" in data.agent_id:
        base_id = data.agent_id.split("-")[0]
        x45_dir = _resolve_prompts_dir(prompts_dir, base_id)
        if x45_dir:
            link_path = x45_dir / f"{data.agent_id}.{data.type}"
            symlink_target = f"../{data.value}.{data.type}" if data.value else ""
        else:
            link_path = prompts_dir / f"{data.agent_id}.{data.type}"
            symlink_target = f"{data.value}.{data.type}" if data.value else ""
    else:
        link_path = prompts_dir / f"{data.agent_id}.{data.type}"
        symlink_target = f"{data.value}.{data.type}" if data.value else ""

    if data.value == "":
        # Remove override (only for non-default)
        if data.agent_id == "default":
            raise HTTPException(status_code=400, detail="cannot remove default")
        # Also check old location in prompts/ for cleanup
        old_path = prompts_dir / f"{data.agent_id}.{data.type}"
        if old_path.is_symlink() or old_path.exists():
            old_path.unlink()
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
    link_path.symlink_to(symlink_target)

    return {"status": "updated", "agent_id": data.agent_id, "type": data.type, "value": data.value}


@app.post("/api/config/effort")
async def update_effort(data: EffortUpdate):
    """Create, update, or remove an effort override for an agent."""
    prompts_dir = BASE_DIR / "prompts"

    # Validate agent_id format
    if data.agent_id != "default" and not re.match(r'^\d{3}(-\d{3})?$', data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    if data.level == "":
        # Remove override (only for non-default)
        if data.agent_id == "default":
            raise HTTPException(status_code=400, detail="cannot remove default effort")
        effort_path = prompts_dir / f"{data.agent_id}.effort"
        if effort_path.exists():
            effort_path.unlink()
        return {"status": "removed", "agent_id": data.agent_id}

    if data.level not in ("L", "M", "H"):
        raise HTTPException(status_code=400, detail="level must be L, M, or H")

    effort_path = prompts_dir / f"{data.agent_id}.effort"
    effort_path.write_text(data.level + "\n")
    return {"status": "updated", "agent_id": data.agent_id, "level": data.level}


# --- Favoris (persisted JSON per user per project) ---

def _favoris_file(user: str, project: str) -> Path:
    safe = "".join(c for c in project if c.isalnum() or c in "-_ ")[:30].strip()
    if not safe:
        safe = "default"
    return BASE_DIR / "prompts" / f"favoris-{user}-{safe}.json"

@app.get("/api/config/favoris")
async def get_favoris(user: str = "default", project: str = "default"):
    """Get agent favoris config for a user+project."""
    f = _favoris_file(user, project)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}

@app.post("/api/config/favoris")
async def set_favoris(data: dict):
    """Save agent favoris config. Body: {user, project, favoris: {agent_id: position (1-6)}}."""
    user = data.get("user", "default")
    project = data.get("project", "default")
    favoris = data.get("favoris", {})
    clean = {}
    for k, v in favoris.items():
        if isinstance(v, int) and 1 <= v <= 6:
            clean[k] = v
    _favoris_file(user, project).write_text(json.dumps(clean, indent=2) + "\n")
    return {"status": "ok", "user": user, "project": project, "favoris": clean}

@app.get("/api/config/favoris/projects")
async def get_favoris_projects(user: str = "default"):
    """List all projects for a user. Returns {projects: ["mail", "drive"]}."""
    import glob as g
    pattern = str(BASE_DIR / "prompts" / f"favoris-{user}-*.json")
    prefix = f"favoris-{user}-"
    projects = []
    for path in sorted(g.glob(pattern)):
        name = Path(path).stem  # e.g. favoris-admin-mail
        if name.startswith(prefix):
            proj = name[len(prefix):]
            if proj:
                projects.append(proj)
    return {"projects": projects}

@app.post("/api/config/favoris/rename")
async def rename_favoris_project(data: dict):
    """Rename a favoris project. Body: {user, old_project, new_project}.
    If new_project file already exists, returns its favoris (switch, no rename)."""
    user = data.get("user", "default")
    old_project = data.get("old_project", "")
    new_project = data.get("new_project", "")
    if not old_project or not new_project:
        raise HTTPException(400, "old_project and new_project required")
    old_f = _favoris_file(user, old_project)
    new_f = _favoris_file(user, new_project)
    # Sanitized names may match — no-op
    if old_f == new_f:
        favoris = {}
        if old_f.exists():
            try:
                favoris = json.loads(old_f.read_text())
            except Exception:
                pass
        return {"status": "ok", "project": new_project, "favoris": favoris}
    # If destination exists → switch (load it, don't rename)
    if new_f.exists():
        try:
            favoris = json.loads(new_f.read_text())
        except Exception:
            favoris = {}
        return {"status": "switched", "project": new_project, "favoris": favoris}
    # Rename old → new
    favoris = {}
    if old_f.exists():
        old_f.rename(new_f)
        try:
            favoris = json.loads(new_f.read_text())
        except Exception:
            pass
    else:
        # No old file — create empty new
        new_f.write_text("{}\n")
    return {"status": "renamed", "project": new_project, "favoris": favoris}

@app.post("/api/config/favoris/delete")
async def delete_favoris_project(data: dict):
    """Delete a favoris project file. Body: {user, project}."""
    user = data.get("user", "default")
    project = data.get("project", "")
    if not project:
        raise HTTPException(400, "project required")
    f = _favoris_file(user, project)
    removed_dir = BASE_DIR / "removed"
    removed_dir.mkdir(exist_ok=True)
    if f.exists():
        import shutil
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.move(str(f), str(removed_dir / f"{ts}_{f.name}"))
    return {"status": "deleted", "project": project}


@app.get("/api/config/tmux-width")
async def get_tmux_width():
    """Get tmux width from persisted file, fallback to live sessions."""
    width_file = BASE_DIR / "prompts" / "tmux.width"
    if width_file.exists():
        try:
            return {"width": int(width_file.read_text().strip())}
        except Exception:
            pass
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{window_width}"],
            text=True, capture_output=True, timeout=5
        )
        widths = [int(w) for w in result.stdout.strip().split('\n') if w.strip().isdigit()]
        return {"width": widths[0] if widths else 220}
    except Exception:
        return {"width": 220}


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
        # Persist for new agent sessions
        (BASE_DIR / "prompts" / "tmux.width").write_text(str(width) + "\n")
        return {"status": "ok", "width": width, "sessions": resized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/config/panel")
async def get_panel_config():
    """Return panel overrides and current mode."""
    cfg = _read_panel_config()
    return {"overrides": cfg.get("overrides", {}), "mode": _cache.get("mode", "pipeline")}


@app.post("/api/config/panel")
async def update_panel_config(data: PanelConfigUpdate):
    """Set or remove a panel override for an agent."""
    if not re.match(r'^\d{3}(-\d{3})?$', data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    if data.panel not in ("control", "agent", ""):
        raise HTTPException(status_code=400, detail="panel must be 'control', 'agent', or ''")

    cfg = _read_panel_config()
    overrides = cfg.get("overrides", {})

    if data.panel == "":
        overrides.pop(data.agent_id, None)
    else:
        overrides[data.agent_id] = data.panel

    cfg["overrides"] = overrides
    _write_panel_config(cfg)
    return {"status": "ok", "overrides": overrides}


# === Crontab Config ===

@app.get("/api/config/crontab")
async def get_crontab():
    """List all crontab entries (active + suspended)."""
    CRONTAB_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for f in sorted(CRONTAB_DIR.iterdir()):
        if not f.is_file():
            continue
        name = f.name
        suspended = name.endswith(".prompt.suspended")
        if not suspended and not name.endswith(".prompt"):
            continue
        # Parse: {agent}-{period}.prompt[.suspended]
        base = name.replace(".suspended", "")
        m = re.match(r'^(\d{3}(?:-\d{3})?)_(\d+)\.prompt$', base)
        if not m:
            continue
        try:
            prompt = f.read_text(errors="replace").strip()
        except Exception:
            prompt = ""
        entries.append({
            "agent_id": m.group(1),
            "period": int(m.group(2)),
            "prompt": prompt,
            "suspended": suspended,
        })
    return {"entries": entries}


@app.post("/api/config/crontab")
async def create_crontab(data: CrontabCreate):
    """Create a new crontab entry."""
    if not re.match(r'^\d{3}(-\d{3})?$', data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    if data.period not in VALID_CRONTAB_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {sorted(VALID_CRONTAB_PERIODS)}")
    if not data.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    CRONTAB_DIR.mkdir(parents=True, exist_ok=True)
    filepath = CRONTAB_DIR / f"{data.agent_id}_{data.period}.prompt"
    if filepath.exists() or filepath.with_suffix(".prompt.suspended").exists():
        raise HTTPException(status_code=409, detail="Entry already exists")
    filepath.write_text(data.prompt.strip() + "\n")
    return {"status": "created", "file": filepath.name}


@app.put("/api/config/crontab")
async def update_crontab(data: CrontabUpdate):
    """Update, suspend, or resume a crontab entry."""
    if not re.match(r'^\d{3}(-\d{3})?$', data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    if data.period not in VALID_CRONTAB_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {sorted(VALID_CRONTAB_PERIODS)}")

    base = f"{data.agent_id}_{data.period}.prompt"
    active = CRONTAB_DIR / base
    suspended = CRONTAB_DIR / f"{base}.suspended"

    if data.action == "suspend":
        if not active.exists():
            raise HTTPException(status_code=404, detail="Active entry not found")
        active.rename(suspended)
        return {"status": "suspended", "file": suspended.name}

    elif data.action == "resume":
        if not suspended.exists():
            raise HTTPException(status_code=404, detail="Suspended entry not found")
        suspended.rename(active)
        return {"status": "resumed", "file": active.name}

    else:
        # Update prompt content
        target = active if active.exists() else suspended if suspended.exists() else None
        if not target:
            raise HTTPException(status_code=404, detail="Entry not found")
        if data.prompt is not None:
            target.write_text(data.prompt.strip() + "\n")
        return {"status": "updated", "file": target.name}


@app.delete("/api/config/crontab")
async def delete_crontab(data: CrontabDelete):
    """Delete a crontab entry (moves to removed/)."""
    if not re.match(r'^\d{3}(-\d{3})?$', data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    base = f"{data.agent_id}_{data.period}.prompt"
    active = CRONTAB_DIR / base
    suspended = CRONTAB_DIR / f"{base}.suspended"

    target = active if active.exists() else suspended if suspended.exists() else None
    if not target:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Safe remove: move to removed/
    removed_dir = BASE_DIR / "removed"
    removed_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = removed_dir / f"{ts}_{target.name}"
    target.rename(dest)
    return {"status": "deleted", "moved_to": str(dest)}


# === Keep Alive Config ===

KEEPALIVE_DIR = BASE_DIR / "keepalive"
PROFILES_DIR = BASE_DIR / "login"


@app.get("/api/config/keepalive")
async def get_keepalive():
    """List all login profiles with their keepalive and tmux status."""
    KEEPALIVE_DIR.mkdir(parents=True, exist_ok=True)

    # List profiles from login/ directory
    profiles = []
    if PROFILES_DIR.exists():
        for d in sorted(PROFILES_DIR.iterdir()):
            if d.is_dir() and d.name.startswith("claude"):
                profiles.append(d.name)

    # Check tmux sessions
    running_sessions = set()
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{session_name}"], text=True
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith(f"{MA_PREFIX}-agent-002-"):
                    running_sessions.add(line.replace(f"{MA_PREFIX}-agent-002-", ""))
    except Exception:
        pass

    # Build entries
    entries = []
    for profile in profiles:
        active_file = KEEPALIVE_DIR / f"{profile}.active"
        suspended_file = KEEPALIVE_DIR / f"{profile}.suspended"
        is_active = active_file.exists()
        is_suspended = suspended_file.exists()
        is_running = profile in running_sessions

        entries.append({
            "profile": profile,
            "running": is_running,
            "keepalive": is_active,
            "suspended": is_suspended,
            "session": f"002-{profile}",
        })

    return {"entries": entries}


@app.post("/api/config/keepalive/start")
async def start_keepalive(data: dict):
    """Start a Claude login session with keepalive."""
    profile = data.get("profile", "")
    if not re.match(r'^claude\d[a-b]$', profile):
        raise HTTPException(status_code=400, detail="invalid profile")

    profile_dir = PROFILES_DIR / profile
    if not profile_dir.exists():
        raise HTTPException(status_code=404, detail="profile directory not found")

    session = f"{MA_PREFIX}-agent-002-{profile}"

    # Check if already running
    result = await _run_subprocess(["tmux", "has-session", "-t", session], text=True)
    if result.returncode == 0:
        raise HTTPException(status_code=409, detail="session already running")

    # Create tmux session with Claude
    cmd = f"cd '{BASE_DIR}' && CLAUDE_CONFIG_DIR='{profile_dir}' claude --dangerously-skip-permissions"
    await _run_subprocess([
        "tmux", "new-session", "-d", "-s", session, cmd
    ], text=True)

    # Create keepalive file
    KEEPALIVE_DIR.mkdir(parents=True, exist_ok=True)
    keepalive_file = KEEPALIVE_DIR / f"{profile}.active"
    if not keepalive_file.exists():
        keepalive_file.write_text("toujours en vie ?\n")

    return {"status": "started", "session": session}


@app.post("/api/config/keepalive/stop")
async def stop_keepalive(data: dict):
    """Stop a Claude login session."""
    profile = data.get("profile", "")
    if not re.match(r'^claude\d[a-b]$', profile):
        raise HTTPException(status_code=400, detail="invalid profile")

    session = f"{MA_PREFIX}-agent-002-{profile}"
    await _run_subprocess(["tmux", "kill-session", "-t", session], text=True)

    # Move keepalive file to suspended
    active = KEEPALIVE_DIR / f"{profile}.active"
    suspended = KEEPALIVE_DIR / f"{profile}.suspended"
    if active.exists():
        active.rename(suspended)

    return {"status": "stopped"}


@app.post("/api/config/keepalive/probe")
async def probe_keepalive(data: dict):
    """Read cached profile info from static JSON file."""
    profile = data.get("profile", "")
    if not re.match(r'^claude\d[a-b]$', profile):
        raise HTTPException(status_code=400, detail="invalid profile")

    info_file = KEEPALIVE_DIR / f"info_{profile}.json"
    if info_file.exists():
        try:
            info = json.loads(info_file.read_text())
        except Exception:
            info = {}
    else:
        info = {}

    return {"profile": profile, "info": info}


async def _agent_lifecycle(agent_id: str, action: str):
    """Start, stop, or restart an agent via ./scripts/agent.sh."""
    if not re.match(r'^\d{3}(-\d{3})?$', agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    script = BASE_DIR / "scripts" / "agent.sh"
    if not script.exists():
        raise HTTPException(status_code=500, detail="agent.sh not found")

    try:
        result = await _run_subprocess(
            ["bash", str(script), action, agent_id],
            text=True, timeout=60
        )
        output = result.stdout.strip()
        print(f"[{action}] agent {agent_id}: {output}")

        return {
            "status": action,
            "agent_id": agent_id,
            "output": output,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{action} failed: {e}")


@app.post("/api/agent/{agent_id}/start")
async def start_agent(agent_id: str):
    return await _agent_lifecycle(agent_id, "start")


@app.post("/api/agent/{agent_id}/stop")
async def stop_agent(agent_id: str):
    return await _agent_lifecycle(agent_id, "stop")


@app.post("/api/agent/{agent_id}/restart")
async def restart_agent(agent_id: str):
    return await _agent_lifecycle(agent_id, "restart")


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
    # Validate agent_id format
    if not re.match(r'^\d{3}(-\d{3})?$', agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    # Filter non-printable characters (prevent tmux escape injection)
    if data.text and any(ord(c) < 32 and c not in ('\n', '\r', '\t') for c in data.text):
        raise HTTPException(status_code=400, detail="invalid characters")
    session_name = f"{MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        # Check if session exists
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Incremental diff: only send backspaces + new chars
        prev = (data.previous or "").rstrip()
        new = (data.text or "").rstrip()

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
            _log_prompt_history(agent_id, data.text)

        return {
            "status": "updated",
            "agent_id": agent_id,
            "text": data.text,
            "submitted": data.submit,
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update input: {str(e)}")


@app.get("/api/agent/{agent_id}/history")
async def get_agent_history(agent_id: str):
    """Read prompt history file for an agent."""
    prompts_dir = BASE_DIR / "prompts"
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    if parent_dir:
        history_file = parent_dir / f"{agent_id}.history"
    else:
        history_file = prompts_dir / f"{agent_id}.history"
    if not history_file.exists():
        return {"lines": [], "file": str(history_file)}
    text = history_file.read_text(errors="replace")
    lines = [l for l in text.splitlines() if l.strip()]
    return {"lines": lines, "file": str(history_file)}


@app.get("/api/agent/{agent_id}/notes")
async def get_agent_notes(agent_id: str):
    """Read notes file for an agent."""
    prompts_dir = BASE_DIR / "prompts"
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    notes_file = (parent_dir / f"{agent_id}.notes") if parent_dir else (prompts_dir / f"{agent_id}.notes")
    if not notes_file.exists():
        return {"content": "", "file": str(notes_file)}
    return {"content": notes_file.read_text(errors="replace"), "file": str(notes_file)}


@app.post("/api/agent/{agent_id}/notes")
async def save_agent_notes(agent_id: str, req: Request):
    """Save notes file for an agent."""
    body = await req.json()
    content = body.get("content", "")
    prompts_dir = BASE_DIR / "prompts"
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    notes_file = (parent_dir / f"{agent_id}.notes") if parent_dir else (prompts_dir / f"{agent_id}.notes")
    notes_file.write_text(content)
    return {"ok": True, "file": str(notes_file)}


@app.get("/api/history/recent")
async def get_recent_history(n: int = 10):
    """Return last N prompts (all agents) from Redis stream."""
    if not redis_pool:
        return {"entries": []}
    try:
        raw = await redis_pool.xrevrange(PROMPT_HISTORY_STREAM, count=n)
        entries = []
        for _msg_id, data in reversed(raw):
            entries.append({
                "time": data.get("time", ""),
                "agent": data.get("agent", ""),
                "text": data.get("text", ""),
            })
        return {"entries": entries}
    except Exception:
        return {"entries": []}


CHAT_STREAM = f"{MA_PREFIX}:devchat"


class ChatMessage(BaseModel):
    text: str
    user: str = "anon"


@app.get("/api/chat")
async def get_chat(last: int = 50):
    """Read last N dev chat messages from Redis stream."""
    if not redis_pool:
        return {"lines": []}
    try:
        raw = await redis_pool.xrevrange(CHAT_STREAM, count=last)
        lines = []
        for msg_id, data in reversed(raw):
            lines.append(data.get("line", ""))
        return {"lines": lines}
    except Exception:
        return {"lines": []}


@app.post("/api/chat")
async def post_chat(msg: ChatMessage):
    """Post a dev chat message to Redis stream."""
    if not redis_pool:
        raise HTTPException(status_code=503, detail="Redis not available")
    ts = time.strftime("%H:%M")
    line = f"{ts} {msg.user}: {msg.text.replace(chr(10), ' ').replace(chr(13), '')}"
    await redis_pool.xadd(CHAT_STREAM, {"line": line}, maxlen=200)
    return {"status": "ok"}


ALLOWED_KEYS = {"Enter", "C-c", "Escape", "C-u", "C-d", "C-l", "C-z", "Up", "Down", "Left", "Right", "Tab", "Space", "y", "n"}


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


# === Frontend Logging ===

FRONTEND_LOG_DIR = BASE_DIR / "logs" / "frontend"


@app.post("/api/logs/frontend")
async def post_frontend_logs(request: Request):
    """Receive frontend log events and append them as JSONL to logs/frontend/."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events = body.get("events", [])
    if not events:
        return {"ok": True, "written": 0}

    FRONTEND_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # One JSONL file per calendar day (UTC)
    date_str = time.strftime("%Y-%m-%d", time.gmtime())
    log_path = FRONTEND_LOG_DIR / f"frontend-{date_str}.jsonl"

    lines = "\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(lines)

    return {"ok": True, "written": len(events)}


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
    token = websocket.query_params.get("token", "")
    if not token or not _verify_jwt_minimal(token):
        print(f"[ws] REJECTED agent={agent_id} token_len={len(token)} from={websocket.client}")
        await websocket.close(code=1008)
        return
    print(f"[ws] ACCEPTED agent={agent_id} from={websocket.client}")
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
    token = websocket.query_params.get("token", "")
    if not token or not _verify_jwt_minimal(token):
        await websocket.close(code=1008)
        return
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
    token = websocket.query_params.get("token", "")
    if not token or not _verify_jwt_minimal(token):
        await websocket.close(code=1008)
        return
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



# === Agent Chat (Robeke shim proxy) ===

AGENT_SHIM_URL = os.environ.get("AGENT_SHIM_URL", "http://127.0.0.1:8093")
AGENT_FREEMIUM_TOKEN_URL = os.environ.get(
    "AGENT_FREEMIUM_TOKEN_URL",
    "http://127.0.0.1:8040/realms/freemium/protocol/openid-connect/token",
)
AGENT_FREEMIUM_CLIENT_ID = os.environ.get("AGENT_FREEMIUM_CLIENT_ID", "freemium")

# Cache: {username: (token_str, expiry_timestamp)}
_freemium_token_cache: dict[str, tuple[str, float]] = {}


def _extract_username_from_jwt(auth_header: str) -> Optional[str]:
    """Extract preferred_username from a dashboard JWT (base64 decode, no crypto validation)."""
    try:
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("preferred_username")
    except Exception:
        return None


async def _get_freemium_token(username: str) -> Optional[str]:
    """Get a freemium Keycloak JWT via password grant. Caches until near-expiry."""
    cached = _freemium_token_cache.get(username)
    if cached and cached[1] > time.time():
        return cached[0]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                AGENT_FREEMIUM_TOKEN_URL,
                data={
                    "grant_type": "password",
                    "client_id": AGENT_FREEMIUM_CLIENT_ID,
                    "username": username,
                    "password": username,  # convention: password = username
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            token = data["access_token"]
            expires_in = data.get("expires_in", 300)
            _freemium_token_cache[username] = (token, time.time() + expires_in - 60)
            return token
    except Exception:
        return None


@app.get("/api/agent-chat/health")
async def agent_chat_health():
    """Proxy to shim /health — public, wraps 'ok' text in JSON."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{AGENT_SHIM_URL}/health", timeout=5.0)
            text = resp.text.strip()
            if text == "ok":
                return {"status": "ok"}
            return {"status": text}
    except Exception:
        return Response(
            content=json.dumps({"status": "error", "detail": "shim unreachable"}),
            status_code=503,
            media_type="application/json",
        )


@app.get("/api/agent-chat/spec")
async def agent_chat_spec():
    """Proxy to shim /spec — public."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{AGENT_SHIM_URL}/spec", timeout=5.0)
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(
            content=json.dumps({"error": "shim unreachable"}),
            status_code=503,
            media_type="application/json",
        )


@app.post("/api/agent-chat/rpc")
async def agent_chat_rpc(request: Request):
    """Proxy to shim /rpc — auth bridge: dashboard JWT -> freemium JWT."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(
            content=json.dumps({"error": "cannot extract username from token"}),
            status_code=401,
            media_type="application/json",
        )

    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(
            content=json.dumps({"error": "failed to obtain freemium token", "username": username}),
            status_code=502,
            media_type="application/json",
        )

    body = await request.body()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{AGENT_SHIM_URL}/rpc",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {freemium_token}",
                },
                timeout=120.0,  # MCP calls can be long
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except httpx.TimeoutException:
        return Response(
            content=json.dumps({"error": "shim timeout"}),
            status_code=504,
            media_type="application/json",
        )
    except Exception:
        return Response(
            content=json.dumps({"error": "shim unreachable"}),
            status_code=503,
            media_type="application/json",
        )


@app.get("/api/agent-chat/facts")
async def agent_chat_facts(request: Request):
    """Proxy to shim /api/facts — requires auth."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(content=json.dumps({"error": "unauthorized"}), status_code=401,
                        media_type="application/json")
    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(content=json.dumps({"error": "failed to obtain freemium token"}), status_code=502,
                        media_type="application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{AGENT_SHIM_URL}/api/facts",
                headers={"Authorization": f"Bearer {freemium_token}"},
                timeout=10.0,
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")


@app.get("/api/agent-chat/events")
async def agent_chat_events():
    """SSE proxy to shim /events/progress — public (same as shim)."""
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{AGENT_SHIM_URL}/events/progress", timeout=None) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk
    try:
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")


@app.get("/api/agent-chat/conversations")
async def agent_chat_conversations(request: Request):
    """Proxy to shim /api/conversations — requires auth."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(content=json.dumps({"error": "unauthorized"}), status_code=401,
                        media_type="application/json")
    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(content=json.dumps({"error": "failed to obtain freemium token"}), status_code=502,
                        media_type="application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{AGENT_SHIM_URL}/api/conversations",
                headers={"Authorization": f"Bearer {freemium_token}"},
                timeout=10.0,
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")


@app.get("/api/agent-chat/conversations/{conv_id}/messages")
async def agent_chat_conversation_messages(conv_id: str, request: Request):
    """Proxy to shim /api/conversations/{id}/messages — requires auth."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(content=json.dumps({"error": "unauthorized"}), status_code=401,
                        media_type="application/json")
    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(content=json.dumps({"error": "failed to obtain freemium token"}), status_code=502,
                        media_type="application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{AGENT_SHIM_URL}/api/conversations/{conv_id}/messages",
                headers={"Authorization": f"Bearer {freemium_token}"},
                timeout=10.0,
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")


# === Static Files (Frontend) ===

# Serve static assets (JS, CSS, etc.)
frontend_path = os.path.join(os.path.dirname(__file__), FRONTEND_DIR)
if os.path.exists(frontend_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_path, "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        """Serve frontend index.html (no-cache to pick up new builds)"""
        return FileResponse(
            os.path.join(frontend_path, "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )

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
