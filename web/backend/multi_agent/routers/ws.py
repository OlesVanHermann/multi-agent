"""Endpoints WebSocket : /ws/agent (fan-out par agent + deltas), /ws/status (B1)."""

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

# Sessions keepalive « 002-<profil> » (claude1a…codex4b) : observables dans le
# panneau Keep Alive comme un agent — l'ID ne matche pas AGENT_ID_RE (NNN-NNN)
# mais la session tmux existe bel et bien (agent-002-<profil>).
_KEEPALIVE_ID_RE = re.compile(r"^002-(?:claude|codex)\d[a-z]$")

# B4 : ticket WS à usage unique — le JWT ne transite plus jamais en query
# string (les ?token= finissent dans les access logs nginx/proxies).
WS_TICKET_TTL = 30
_WS_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")


def _ws_ticket_key(ticket: str) -> str:
    return f"wsticket:{ticket}"


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


_ws_agent_connections: list[WebSocket] = []
_WS_AGENT_MAX = 100

# ────────────────────────────────────────────────────────────────────
# Fan-out par agent : UNE boucle de capture tmux par agent observé,
# partagée par tous les WS abonnés — le coût serveur est proportionnel
# aux agents regardés, plus au nombre de navigateurs.
#
# Protocole : premier message d'un abonné = snapshot complet {type:
# "output"} ; ensuite des deltas {type: "output_delta", keep, append} où
# keep = nombre de lignes du préfixe commun conservées et append = lignes
# qui remplacent la suite (new == old[:keep] + append). Un redraw du bas
# d'écran coûte ainsi ~1-4 Ko par tick au lieu du buffer complet (~200 Ko).
# ────────────────────────────────────────────────────────────────────

_CAPTURE_LINES = 3000


def _line_delta(old: list, new: list):
    """(keep, append) tel que new == old[:keep] + append."""
    keep = 0
    limit = min(len(old), len(new))
    while keep < limit and old[keep] == new[keep]:
        keep += 1
    return keep, new[keep:]


class _AgentWatcher:
    """Boucle de capture unique pour un agent, diffusée à N abonnés."""

    GRACE_EMPTY = 5.0   # survie sans abonné (couvre les reconnexions rapides)
    QUEUE_MAX = 20      # client lent → purge + resync par snapshot complet

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.queues = set()
        self.lines = None          # dernier output capturé (liste de lignes)
        self.last_input = ""
        self.poll = 10.0           # l'abonné le plus rapide donne la cadence
        self.task = None

    def _snapshot(self) -> dict:
        return {
            "type": "output",
            "agent_id": self.agent_id,
            "output": "\n".join(self.lines or []),
            "timestamp": int(time.time()),
        }

    def subscribe(self, poll: float):
        q = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self.queues.add(q)
        self.poll = min(self.poll, poll)
        if self.lines is not None:
            q.put_nowait(self._snapshot())
            if self.last_input:
                q.put_nowait({"type": "input_sync", "agent_id": self.agent_id,
                              "current_input": self.last_input,
                              "timestamp": int(time.time())})
        return q

    def unsubscribe(self, q) -> None:
        self.queues.discard(q)

    def _broadcast(self, payload: dict) -> None:
        for q in list(self.queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Client trop lent pour suivre les deltas : purge de sa file
                # puis resynchronisation sur un snapshot complet.
                while True:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                q.put_nowait(self._snapshot())

    async def run(self) -> None:
        empty_since = None
        try:
            while True:
                if not self.queues:
                    if empty_since is None:
                        empty_since = time.time()
                    elif time.time() - empty_since > self.GRACE_EMPTY:
                        return
                    await asyncio.sleep(0.5)
                    continue
                empty_since = None

                result = await _capture_agent_pane(self.agent_id, lines=_CAPTURE_LINES, ansi=False)
                if result.returncode != 0:
                    self._broadcast({"type": "error",
                                     "message": f"Agent {self.agent_id} session not found"})
                    return

                current = result.stdout.rstrip("\n ").split("\n")
                now = int(time.time())
                if self.lines is None:
                    self.lines = current
                    self._broadcast(self._snapshot())
                elif current != self.lines:
                    keep, append = _line_delta(self.lines, current)
                    self.lines = current
                    self._broadcast({"type": "output_delta", "agent_id": self.agent_id,
                                     "keep": keep, "append": append, "timestamp": now})

                # Capture ANSI courte (20 lignes) pour détecter l'input tapé
                result_ansi = await _capture_agent_pane(self.agent_id, ansi=True)
                current_input = _extract_current_input(result_ansi.stdout)
                if current_input != self.last_input:
                    self.last_input = current_input
                    self._broadcast({"type": "input_sync", "agent_id": self.agent_id,
                                     "current_input": current_input, "timestamp": now})

                await asyncio.sleep(self.poll)
        finally:
            if _watchers.get(self.agent_id) is self:
                del _watchers[self.agent_id]


_watchers: dict = {}


def _get_watcher(agent_id: str) -> _AgentWatcher:
    w = _watchers.get(agent_id)
    if w is None or (w.task and w.task.done()):
        w = _AgentWatcher(agent_id)
        w.task = asyncio.create_task(w.run())
        _watchers[agent_id] = w
    return w


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
    # Auth évaluée une seule fois (le ticket est à usage unique) ; les sessions
    # authentifiées sont exemptes du rate limit par IP (navigateurs multiples
    # derrière une même IP publique).
    authenticated = await _ws_authenticated(websocket)
    if not authenticated and not await _check_rate_limit(client_ip):
        await _reject(websocket, 4002)
        return
    if not _ws_origin_ok(websocket):
        await websocket.close(code=1008)
        return
    if not cfg.AGENT_ID_RE.match(agent_id) and not _KEEPALIVE_ID_RE.match(agent_id):
        await websocket.close(code=1008)
        return
    if not authenticated:
        print(f"[ws] REJECTED agent={agent_id} from={websocket.client}")
        await _reject(websocket, 4001)
        return
    # 000 (Architect) : flux AUTORISÉ — cet endpoint est en lecture seule
    # (seuls les pings client sont traités). Les contrôles du 000 restent
    # interdits par les routes REST (403 sur send/input/lifecycle).
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

    # Serialize sends so the heartbeat reader and the fan-out forwarder
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
    watcher = _get_watcher(agent_id)
    queue = watcher.subscribe(poll)

    try:
        while True:
            get_task = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {get_task, ping_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if get_task not in done:
                # heartbeat_reader terminé = client ou proxy parti
                get_task.cancel()
                break
            payload = get_task.result()
            await safe_send(payload)
            if payload.get("type") == "error":
                break

    except Exception as exc:
        # Any disconnect (WebSocketDisconnect, ConnectionResetError,
        # IncompleteReadError, ConnectionClosedError, ClientDisconnected)
        # is normal — the client or proxy closed the connection.
        _ws_close_reason = f"{type(exc).__name__}: {getattr(exc, 'code', '') or str(exc)[:80]}"
    finally:
        watcher.unsubscribe(queue)
        if websocket in _ws_agent_connections:
            _ws_agent_connections.remove(websocket)
        ping_task.cancel()
        _ws_duration = time.time() - _ws_started_at
        print(f"[ws] CLOSED agent={agent_id} from={websocket.client} duration={_ws_duration:.1f}s reason={_ws_close_reason}")


# NOTE : l'endpoint /ws/messages a été supprimé — plus utilisé par le
# frontend, et sa boucle ne détectait jamais la déconnexion du client
# (le broadcast avalait les erreurs d'envoi) : chaque connexion morte
# continuait de SCANner Redis indéfiniment.


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for agent status updates — reads from background cache"""
    client_ip = websocket.headers.get("x-real-ip") or (websocket.client.host if websocket.client else "unknown")
    authenticated = await _ws_authenticated(websocket)
    if not authenticated and not await _check_rate_limit(client_ip):
        await websocket.close(code=1008)
        return
    if not _ws_origin_ok(websocket):
        await websocket.close(code=1008)
        return
    if not authenticated:
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
