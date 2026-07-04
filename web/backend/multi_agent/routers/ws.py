"""Endpoints WebSocket : /ws/agent, /ws/messages, /ws/status (B1)."""

import asyncio
import json
import re
import secrets
import time

from fastapi import APIRouter, HTTPException, WebSocket

from .. import config as cfg
from .. import state
from ..auth import ACCESS_COOKIE, _verify_jwt_minimal
from ..ratelimit import _check_rate_limit
from ..tmuxio import _capture_agent_pane, _extract_current_input

router = APIRouter()

_WS_ALLOWED_ORIGINS = set(cfg._ALLOWED_ORIGINS + cfg._ALLOWED_ORIGINS_LOCAL_DEV)

# B4 : ticket WS à usage unique — le JWT ne transite plus jamais en query
# string (les ?token= finissent dans les access logs nginx/proxies).
WS_TICKET_TTL = 30
_WS_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")


def _ws_ticket_key(ticket: str) -> str:
    return f"{cfg.MA_PREFIX}:wsticket:{ticket}"


@router.post("/api/ws-ticket")
async def create_ws_ticket():
    """Ticket opaque court (TTL 30 s) ; l'auth JWT est déjà imposée par le middleware."""
    if not state.redis_pool:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    ticket = secrets.token_urlsafe(32)
    try:
        await state.redis_pool.setex(_ws_ticket_key(ticket), WS_TICKET_TTL, "1")
    except Exception:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"ticket": ticket, "expires_in": WS_TICKET_TTL}


async def _consume_ws_ticket(ticket: str) -> bool:
    """Valide ET invalide le ticket (DEL atomique → non rejouable)."""
    if not ticket or not _WS_TICKET_RE.match(ticket) or not state.redis_pool:
        return False
    try:
        return bool(await state.redis_pool.delete(_ws_ticket_key(ticket)))
    except Exception:
        return False


async def _ws_authenticated(websocket: WebSocket) -> bool:
    """Auth WS (B4) : ticket à usage unique, sinon cookie HttpOnly (jamais de JWT en URL)."""
    if await _consume_ws_ticket(websocket.query_params.get("ticket", "")):
        return True
    cookie_token = websocket.cookies.get(ACCESS_COOKIE, "")
    return bool(cookie_token) and _verify_jwt_minimal(cookie_token)


def _ws_origin_ok(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin", "")
    if not origin:
        return True
    if "*" in _WS_ALLOWED_ORIGINS:
        return True
    return origin in _WS_ALLOWED_ORIGINS


async def _reject(websocket: WebSocket, code: int) -> None:
    """Deliver a custom close code to the browser.

    A close BEFORE accept() is turned into an HTTP 403 handshake failure by
    uvicorn — the browser never receives the 4xxx code and reports a generic
    1006, so the UI shows 'disconnected' instead of the real cause. Accepting
    first, then closing, sends a proper close frame carrying the code.
    """
    try:
        await websocket.accept()
        await websocket.close(code=code)
    except Exception:
        pass


class ConnectionManager:
    """Manage WebSocket connections"""

    MAX_CONNECTIONS = 200

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> bool:
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            await websocket.close(code=1013)
            return False
        await websocket.accept()
        self.active_connections.append(websocket)
        return True

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

_ws_agent_connections: list[WebSocket] = []
_WS_AGENT_MAX = 100


@router.websocket("/ws/agent/{agent_id}")
async def websocket_agent_output(websocket: WebSocket, agent_id: str):
    """WebSocket endpoint for real-time agent tmux output with input sync.

    Custom close codes (4xxx range reserved for user-defined) so the frontend
    can show the cause of disconnection:
      4001 = JWT invalid/missing
      4002 = rate limit exceeded
      4005 = agent 000 forbidden
      1008 = other policy violation (origin, bad agent_id format)
      1013 = server overloaded (max connections)
    """
    client_ip = websocket.headers.get("x-real-ip") or (websocket.client.host if websocket.client else "unknown")
    if not await _check_rate_limit(client_ip):
        await _reject(websocket, 4002)
        return
    if not _ws_origin_ok(websocket):
        await websocket.close(code=1008)
        return
    if not cfg.AGENT_ID_RE.match(agent_id):
        await websocket.close(code=1008)
        return
    if not await _ws_authenticated(websocket):
        print(f"[ws] REJECTED agent={agent_id} from={websocket.client}")
        await _reject(websocket, 4001)
        return
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    if base_id == "000":
        await _reject(websocket, 4005)
        return
    if len(_ws_agent_connections) >= _WS_AGENT_MAX:
        await _reject(websocket, 1013)
        return
    print(f"[ws] ACCEPTED agent={agent_id} from={websocket.client}")
    await websocket.accept()
    _ws_agent_connections.append(websocket)
    _ws_started_at = time.time()
    _ws_close_reason = "normal"

    try:
        poll = float(websocket.query_params.get("poll", "2.0"))
    except (ValueError, TypeError):
        poll = 2.0
    poll = max(0.5, min(poll, 10.0))

    last_output = ""
    last_input = ""

    # Serialize sends so the heartbeat reader and the main poll loop
    # do not interleave bytes on the ASGI send channel.
    send_lock = asyncio.Lock()

    async def safe_send(payload: dict):
        async with send_lock:
            await websocket.send_json(payload)

    async def heartbeat_reader():
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                if isinstance(data, dict) and data.get("type") == "ping":
                    await safe_send({"type": "pong"})
        except Exception:
            pass

    ping_task = asyncio.create_task(heartbeat_reader())

    try:
        while True:
            if ping_task.done():
                break

            result = await _capture_agent_pane(agent_id, lines=3000, ansi=False)

            if result.returncode != 0:
                await safe_send({
                    "type": "error",
                    "message": f"Agent {agent_id} session not found"
                })
                break

            current_output = result.stdout.rstrip('\n ')

            # Capture with ANSI for input detection (suggestion vs typed)
            result_ansi = await _capture_agent_pane(agent_id, ansi=True)
            current_input = _extract_current_input(result_ansi.stdout)

            # Send output if changed
            if current_output != last_output:
                await safe_send({
                    "type": "output",
                    "agent_id": agent_id,
                    "output": current_output,
                    "timestamp": int(time.time())
                })
                last_output = current_output

            # Send input if changed (separate message for input sync)
            if current_input != last_input:
                await safe_send({
                    "type": "input_sync",
                    "agent_id": agent_id,
                    "current_input": current_input,
                    "timestamp": int(time.time())
                })
                last_input = current_input

            await asyncio.sleep(poll)

    except Exception as exc:
        # Any disconnect (WebSocketDisconnect, ConnectionResetError,
        # IncompleteReadError, ConnectionClosedError, ClientDisconnected)
        # is normal — the client or proxy closed the connection.
        _ws_close_reason = f"{type(exc).__name__}: {getattr(exc, 'code', '') or str(exc)[:80]}"
    finally:
        if websocket in _ws_agent_connections:
            _ws_agent_connections.remove(websocket)
        ping_task.cancel()
        _ws_duration = time.time() - _ws_started_at
        print(f"[ws] CLOSED agent={agent_id} from={websocket.client} duration={_ws_duration:.1f}s reason={_ws_close_reason}")


@router.websocket("/ws/messages")
async def websocket_messages(websocket: WebSocket):
    """WebSocket endpoint for real-time agent messages"""
    client_ip = websocket.headers.get("x-real-ip") or (websocket.client.host if websocket.client else "unknown")
    if not await _check_rate_limit(client_ip):
        await websocket.close(code=1008)
        return
    if not _ws_origin_ok(websocket):
        await websocket.close(code=1008)
        return
    if not await _ws_authenticated(websocket):
        await websocket.close(code=1008)
        return
    if not await manager.connect(websocket):
        return

    try:
        # Track last seen message IDs per stream
        last_ids = {}

        while True:
            if not state.redis_pool:
                await asyncio.sleep(1)
                continue

            # Get all agent outbox streams
            cursor = 0
            streams = {}
            while True:
                cursor, keys = await state.redis_pool.scan(cursor, match=f"{cfg.MA_PREFIX}:agent:*:outbox", count=100)
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
                result = await state.redis_pool.xread(streams, block=1000, count=10)

                for stream_name, messages in result:
                    for msg_id, data in messages:
                        last_ids[stream_name] = msg_id

                        # Extract agent ID from stream name
                        parts = stream_name.split(":")
                        raw_aid = parts[2] if len(parts) >= 3 else "unknown"
                        agent_id = raw_aid if cfg.AGENT_ID_RE.match(raw_aid) else "unknown"

                        _WS_ALLOWED_KEYS = {"prompt", "response", "from_agent", "to_agent", "timestamp", "type", "status", "chunk", "text"}
                        safe_data = {k: v for k, v in data.items() if isinstance(k, str) and k in _WS_ALLOWED_KEYS and len(str(v)) < 10000}
                        await manager.broadcast({
                            "type": "message",
                            "agent_id": agent_id,
                            "msg_id": msg_id,
                            "data": safe_data,
                            "timestamp": int(time.time())
                        })
            except Exception as e:
                print(f"WebSocket stream error: {e}")
                await asyncio.sleep(0.5)

    except Exception:
        manager.disconnect(websocket)


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for agent status updates — reads from background cache"""
    client_ip = websocket.headers.get("x-real-ip") or (websocket.client.host if websocket.client else "unknown")
    if not await _check_rate_limit(client_ip):
        await websocket.close(code=1008)
        return
    if not _ws_origin_ok(websocket):
        await websocket.close(code=1008)
        return
    if not await _ws_authenticated(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    _ws_started_at = time.time()
    _ws_close_reason = "normal"

    # Poll interval from query param (default 5s, min = cache interval)
    try:
        poll = float(websocket.query_params.get("poll", "5"))
    except (ValueError, TypeError):
        poll = 5.0
    poll = max(cfg.CACHE_REFRESH_INTERVAL, min(poll, 60))

    last_sent = ""  # JSON string of last sent data to avoid sending duplicates

    send_lock = asyncio.Lock()

    async def safe_send(payload: dict):
        async with send_lock:
            await websocket.send_json(payload)

    async def heartbeat_reader():
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                if isinstance(data, dict) and data.get("type") == "ping":
                    await safe_send({"type": "pong"})
        except Exception:
            pass

    ping_task = asyncio.create_task(heartbeat_reader())

    try:
        while True:
            if ping_task.done():
                break

            agents = state._cache["agents"]
            payload = {
                "type": "status_update",
                "agents": [{"id": a["id"], "status": a["status"], "last_seen": a["last_seen"]} for a in agents],
                "timestamp": state._cache["timestamp"],
            }
            if state._cache.get("mode"):
                payload["mode"] = state._cache["mode"]
            if state._cache.get("triangles"):
                payload["triangles"] = state._cache["triangles"]
            if state._cache.get("agent_names"):
                payload["agent_names"] = state._cache["agent_names"]
            payload_str = json.dumps(payload, sort_keys=True)

            # Only send if data changed
            if payload_str != last_sent:
                await safe_send(payload)
                last_sent = payload_str

            await asyncio.sleep(poll)

    except Exception as exc:
        _ws_close_reason = f"{type(exc).__name__}: {getattr(exc, 'code', '') or str(exc)[:80]}"
    finally:
        ping_task.cancel()
        _ws_duration = time.time() - _ws_started_at
        print(f"[ws] CLOSED endpoint=ws/status from={websocket.client} duration={_ws_duration:.1f}s reason={_ws_close_reason}")
