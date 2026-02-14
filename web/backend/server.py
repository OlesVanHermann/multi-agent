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
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import json
import base64
import hashlib
import hmac

import redis.asyncio as redis
import httpx

# Simple auth fallback (only used when Keycloak is unavailable)
# Empty by default — all auth goes through Keycloak
# For local dev without Keycloak, set SIMPLE_AUTH env var:
#   SIMPLE_AUTH="user:pass:admin" python3 -m uvicorn server:app ...
SIMPLE_AUTH_USERS = {}
_simple_auth = os.environ.get("SIMPLE_AUTH", "")
if _simple_auth:
    for entry in _simple_auth.split(","):
        parts = entry.strip().split(":")
        if len(parts) >= 2:
            SIMPLE_AUTH_USERS[parts[0]] = {
                "password": parts[1],
                "email": f"{parts[0]}@multi-agent.local",
                "name": parts[0].capitalize(),
                "roles": [parts[2]] if len(parts) > 2 else ["viewer"]
            }

# Secret for signing simple tokens
_TOKEN_SECRET = hashlib.sha256(b"multi-agent-local-dev").hexdigest()

# Frontend static files path
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "../frontend/dist")

# Keycloak URL for auth proxy
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")

# Config
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "ma")
CONTEXT_WARNING_THRESHOLD = int(os.environ.get("CONTEXT_WARNING_THRESHOLD", "50"))

# Redis connection pool
redis_pool: Optional[redis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events"""
    global redis_pool
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

    yield

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


# === Routes ===

@app.get("/api/health")
async def health():
    """Health check"""
    redis_ok = False
    if redis_pool:
        try:
            await redis_pool.ping()
            redis_ok = True
        except Exception:
            pass

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "timestamp": int(time.time())
    }


# Cache for _get_agent_states to avoid hammering tmux every few seconds
_agent_states_cache = {"data": {}, "timestamp": 0}
_agent_states_cache_ttl = 3  # seconds


def _get_agent_states() -> dict:
    """Check ALL agent tmux sessions in ONE subprocess (cached).

    Returns dict[agent_id] = {'busy': bool, 'compacted': bool}
    - busy: last 3 lines contain 'esc to interrupt'
    - compacted: last 200 lines contain 'auto-compact' (context compaction message)

    Uses 3-second cache to avoid overwhelming tmux with concurrent WebSocket polls.
    """
    # Return cached data if fresh
    now = time.time()
    if now - _agent_states_cache["timestamp"] < _agent_states_cache_ttl:
        return _agent_states_cache["data"]

    # Recalculate
    try:
        script = (
            f'for s in $(tmux ls -F "#{{session_name}}" 2>/dev/null | grep "^{MA_PREFIX}-agent-"); do '
            f'id="${{s#{MA_PREFIX}-agent-}}"; '
            f'busy=0; compacted=0; '
            f'if tmux capture-pane -t "$s:0.0" -p -J 2>/dev/null | grep "bypass permissions" | tail -1 | grep -q "esc to interrupt"; then busy=1; fi; '
            f'if tmux capture-pane -t "$s:0.0" -p -J -S -200 2>/dev/null | grep -qiE "auto-compact|compacting conversation"; then compacted=1; fi; '
            f'echo "$id:$busy:$compacted"; '
            f'done'
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=15
        )
        states = {}
        for line in result.stdout.strip().split('\n'):
            if ':' not in line:
                continue
            parts = line.split(':')
            if len(parts) >= 3:
                agent_id = parts[0]
                states[agent_id] = {
                    'busy': parts[1] == '1',
                    'compacted': parts[2] == '1',
                }

        # Update cache
        _agent_states_cache["data"] = states
        _agent_states_cache["timestamp"] = now
        return states
    except Exception:
        return {}


async def _trigger_prompt_reload(agent_id: str):
    """Send reload_prompt to an agent with 60s debounce."""
    if not redis_pool:
        return
    debounce_key = f"{MA_PREFIX}:agent:{agent_id}:last_reload"
    try:
        last = await redis_pool.get(debounce_key)
        if last and time.time() - float(last) < 60:
            return  # debounce: too soon
        await redis_pool.set(debounce_key, str(time.time()), ex=120)
        await redis_pool.xadd(f"{MA_PREFIX}:agent:{agent_id}:inbox", {
            'type': 'reload_prompt',
            'from_agent': 'server',
            'timestamp': str(int(time.time())),
        })
        print(f"Triggered prompt reload for agent {agent_id}")
    except Exception as e:
        print(f"Failed to trigger reload for {agent_id}: {e}")


async def _resolve_agent_status(agent_id: str, tmux_state: dict, messages_since_reload: int) -> str:
    """Determine agent context status with sticky compacting state.

    Once auto-compact is detected, the state persists in Redis until the
    agent digests the reloaded prompt (messages_since_reload drops to 0).
    """
    compacting_key = f"{MA_PREFIX}:agent:{agent_id}:compacting"

    # If tmux shows auto-compact NOW, latch the sticky flag
    if tmux_state.get('compacted') and redis_pool:
        try:
            await redis_pool.set(compacting_key, "1", ex=600)  # TTL 10min safety
        except Exception:
            pass

    # Check sticky flag
    is_compacting = False
    if redis_pool:
        try:
            is_compacting = await redis_pool.get(compacting_key) is not None
        except Exception:
            pass

    # Prompt digested → clear sticky flag, back to normal
    if is_compacting and messages_since_reload == 0:
        if redis_pool:
            try:
                await redis_pool.delete(compacting_key)
                await redis_pool.delete(f"{MA_PREFIX}:agent:{agent_id}:reload_sent")
            except Exception:
                pass
        is_compacting = False

    # Return status (priority: compacted > warning > busy)
    if is_compacting:
        # Trigger reload ONCE per compaction (bridge handles /reset to clear thinking blocks)
        reload_sent_key = f"{MA_PREFIX}:agent:{agent_id}:reload_sent"
        if redis_pool:
            try:
                reload_sent = await redis_pool.get(reload_sent_key)
                if not reload_sent:
                    await redis_pool.set(reload_sent_key, "1", ex=600)
                    asyncio.ensure_future(_trigger_prompt_reload(agent_id))
            except Exception:
                pass
        return "context_compacted"
    elif messages_since_reload >= CONTEXT_WARNING_THRESHOLD:
        return "context_warning"
    elif tmux_state.get('busy'):
        return "busy"

    return ""  # no override


@app.get("/api/agents")
async def list_agents():
    """List all agents with active tmux sessions"""
    agents = []
    agent_states = _get_agent_states()  # ONE subprocess for all agents

    # Get active tmux sessions (agent-XXX format)
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith(f"{MA_PREFIX}-agent-"):
                    agent_id = line.replace(f"{MA_PREFIX}-agent-", "")
                    if agent_id.isdigit():
                        # Default: tmux session exists = agent is active
                        status = "active"
                        last_seen = int(time.time())
                        queue_size = 0
                        tasks_completed = 0
                        messages_since_reload = 0

                        if redis_pool:
                            try:
                                data = await redis_pool.hgetall(f"{MA_PREFIX}:agent:{agent_id}")
                                if data:
                                    hb_last_seen = int(data.get("last_seen", 0))
                                    queue_size = int(data.get("queue_size", 0))
                                    tasks_completed = int(data.get("tasks_completed", 0))
                                    messages_since_reload = int(data.get("messages_since_reload", 0))

                                    # Always use Redis status (it's the last known state)
                                    # Heartbeat just tells us how old this state is
                                    status = data.get("status", "active")
                                    last_seen = hb_last_seen
                            except Exception:
                                pass

                        # Determine status from tmux state (sticky compacting)
                        state = agent_states.get(agent_id, {})
                        override = await _resolve_agent_status(agent_id, state, messages_since_reload)
                        if override:
                            status = override

                        agents.append(AgentStatus(
                            id=agent_id,
                            status=status,
                            last_seen=last_seen,
                            queue_size=queue_size,
                            tasks_completed=tasks_completed,
                            mode="tmux"
                        ))
    except Exception as e:
        print(f"Error listing tmux sessions: {e}")

    # Sort by agent ID
    agents.sort(key=lambda a: int(a.id))

    return {
        "agents": [a.model_dump() for a in agents],
        "count": len(agents),
        "timestamp": int(time.time())
    }


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
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Send message via tmux send-keys
        subprocess.run(
            ["tmux", "send-keys", "-t", target, msg.message, "Enter"],
            check=True
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
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True
        )
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
            subprocess.run(
                ["tmux", "send-keys", "-t", target] + ["BSpace"] * bs,
                check=True
            )

        # Type new chars
        new_chars = new[i:]
        if new_chars:
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "-l", new_chars],
                check=True
            )

        # Submit if requested
        if data.submit:
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                check=True
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
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        for key in data.keys:
            if key not in ALLOWED_KEYS:
                raise HTTPException(status_code=400, detail=f"Key not allowed: {key}")
            subprocess.run(
                ["tmux", "send-keys", "-t", target, key],
                check=True
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
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Capture pane content (plain for display)
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-J", "-S", f"-{lines}"],
            capture_output=True,
            text=True
        )
        output = result.stdout.rstrip('\n ')

        # Capture with ANSI codes for input detection (suggestion vs typed)
        result_ansi = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-e", "-S", "-20"],
            capture_output=True,
            text=True
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

def _make_simple_token(username: str, user_info: dict) -> str:
    """Create a simple base64-encoded JWT-like token for local auth."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_data = {
        "sub": username,
        "preferred_username": username,
        "email": user_info["email"],
        "name": user_info["name"],
        "roles": user_info["roles"],
        "realm_access": {"roles": user_info["roles"]},
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400,
    }
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).decode().rstrip("=")
    sig = hmac.new(_TOKEN_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"{header}.{payload}.{sig}"


@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_keycloak(request: Request, path: str):
    """Auth endpoint: tries Keycloak first, falls back to simple local auth."""

    # Handle token requests locally if Keycloak is unavailable
    if "openid-connect/token" in path and request.method == "POST":
        body = await request.body()
        params = dict(x.split("=", 1) for x in body.decode().split("&") if "=" in x)

        from urllib.parse import unquote_plus
        username = unquote_plus(params.get("username", ""))
        password = unquote_plus(params.get("password", ""))

        # Try Keycloak first
        url = f"{KEYCLOAK_URL}/{path}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host"]}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method="POST", url=url, headers=headers, content=body,
                    params=request.query_params, timeout=5.0
                )
                # Accept Keycloak response if client is configured
                # Fall through to simple auth on invalid_client (realm/client not set up)
                if response.status_code < 500:
                    try:
                        resp_body = response.json()
                        if resp_body.get("error") == "invalid_client":
                            pass  # Fall through to simple auth
                        else:
                            return Response(content=response.content, status_code=response.status_code,
                                            headers=dict(response.headers))
                    except Exception:
                        return Response(content=response.content, status_code=response.status_code,
                                        headers=dict(response.headers))
        except Exception:
            pass  # Keycloak not available, use simple auth

        # Simple local auth fallback
        user_info = SIMPLE_AUTH_USERS.get(username)
        if user_info and user_info["password"] == password:
            token = _make_simple_token(username, user_info)
            return Response(
                content=json.dumps({
                    "access_token": token,
                    "refresh_token": token,
                    "token_type": "Bearer",
                    "expires_in": 86400,
                }),
                status_code=200,
                headers={"Content-Type": "application/json"},
            )
        else:
            return Response(
                content=json.dumps({"error": "invalid_grant", "error_description": "Invalid credentials"}),
                status_code=401,
                headers={"Content-Type": "application/json"},
            )

    # For other auth paths, proxy to Keycloak
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
            raise HTTPException(status_code=502, detail=f"Keycloak proxy error: {str(e)}")


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
    poll = float(websocket.query_params.get("poll", "1.0"))
    poll = max(0.2, min(poll, 10.0))  # Clamp 0.2-10s

    session_name = f"{MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"
    last_output = ""
    last_input = ""

    try:
        while True:
            # Capture pane content (plain for display)
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", target, "-p", "-J", "-S", "-500"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Agent {agent_id} session not found"
                })
                break

            current_output = result.stdout.rstrip('\n ')

            # Capture with ANSI for input detection (suggestion vs typed)
            result_ansi = subprocess.run(
                ["tmux", "capture-pane", "-t", target, "-p", "-e", "-S", "-20"],
                capture_output=True,
                text=True,
                timeout=5
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

    except (WebSocketDisconnect, ConnectionResetError):
        pass
    except Exception as e:
        import traceback
        print(f"Agent WebSocket error: {type(e).__name__}: {e}")
        traceback.print_exc()


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

    except (WebSocketDisconnect, ConnectionResetError):
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)
        import traceback
        print(f"Messages WebSocket error: {type(e).__name__}: {e}")
        traceback.print_exc()


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for agent status updates (polling tmux sessions)"""
    await websocket.accept()

    # Poll interval from query param (default 10s)
    poll = float(websocket.query_params.get("poll", "10"))
    poll = max(2, min(poll, 60))  # Clamp 2-60s

    try:
        while True:
            agents = []
            agent_states = _get_agent_states()  # ONE subprocess for all agents

            # Get active tmux sessions
            try:
                result = subprocess.run(
                    ["tmux", "list-sessions", "-F", "#{session_name}"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if line.startswith(f"{MA_PREFIX}-agent-"):
                            agent_id = line.replace(f"{MA_PREFIX}-agent-", "")
                            if agent_id.isdigit():
                                # Default: tmux exists = agent is active
                                status = "active"
                                last_seen = int(time.time())
                                messages_since_reload = 0

                                if redis_pool:
                                    try:
                                        data = await redis_pool.hgetall(f"{MA_PREFIX}:agent:{agent_id}")
                                        if data:
                                            hb_last_seen = int(data.get("last_seen", 0))
                                            messages_since_reload = int(data.get("messages_since_reload", 0))
                                            # Always use Redis status (it's the last known state)
                                            status = data.get("status", "active")
                                            last_seen = hb_last_seen
                                    except Exception:
                                        pass

                                # Determine status from tmux state (sticky compacting)
                                state = agent_states.get(agent_id, {})
                                override = await _resolve_agent_status(agent_id, state, messages_since_reload)
                                if override:
                                    status = override

                                agents.append({
                                    "id": agent_id,
                                    "status": status,
                                    "last_seen": last_seen,
                                })
            except Exception as e:
                print(f"Error listing tmux sessions: {e}")

            agents.sort(key=lambda a: int(a["id"]))

            await websocket.send_json({
                "type": "status_update",
                "agents": agents,
                "timestamp": int(time.time())
            })

            await asyncio.sleep(poll)

    except (WebSocketDisconnect, ConnectionResetError):
        pass
    except Exception as e:
        import traceback
        print(f"Status WebSocket error: {type(e).__name__}: {e}")
        traceback.print_exc()


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
    uvicorn.run(app, host="0.0.0.0", port=8000)
