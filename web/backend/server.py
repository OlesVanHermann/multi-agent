#!/usr/bin/env python3
"""
Multi-Agent Dashboard Backend
FastAPI server exposing agent status and WebSocket streams
"""

import os
import asyncio
import time
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis.asyncio as redis

# Config
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "ma")

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


# === Dashboard HTML ===

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Multi-Agent Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }
  .header { background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 20px; color: #58a6ff; }
  .header .prefix { background: #238636; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }
  .header .count { color: #8b949e; font-size: 14px; margin-left: auto; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; padding: 24px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; transition: border-color 0.2s; }
  .card:hover { border-color: #58a6ff; }
  .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .agent-id { font-size: 24px; font-weight: 700; color: #f0f6fc; }
  .status { padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
  .status.idle { background: #238636; color: #fff; }
  .status.busy { background: #d29922; color: #fff; }
  .status.error, .status.stopped { background: #da3633; color: #fff; }
  .status.unknown { background: #484f58; color: #c9d1d9; }
  .card-body { font-size: 13px; color: #8b949e; }
  .card-body .row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #21262d; }
  .card-body .row:last-child { border-bottom: none; }
  .card-body .label { color: #8b949e; }
  .card-body .value { color: #c9d1d9; font-weight: 500; }
  .stale { opacity: 0.5; }
  .messages { background: #161b22; border: 1px solid #30363d; border-radius: 8px; margin: 0 24px 24px; padding: 16px; max-height: 300px; overflow-y: auto; }
  .messages h2 { font-size: 14px; color: #58a6ff; margin-bottom: 8px; }
  .msg { font-size: 12px; padding: 4px 0; border-bottom: 1px solid #21262d; font-family: monospace; }
  .msg .from { color: #d29922; }
  .msg .time { color: #484f58; }
  .refresh-info { text-align: center; color: #484f58; font-size: 12px; padding: 8px; }
</style>
</head>
<body>
<div class="header">
  <h1>Multi-Agent Dashboard</h1>
  <span class="prefix" id="prefix">--</span>
  <span class="count" id="agent-count">Loading...</span>
</div>
<div class="grid" id="agent-grid"></div>
<div class="messages">
  <h2>Recent Messages</h2>
  <div id="msg-list"><em style="color:#484f58">Connecting...</em></div>
</div>
<div class="refresh-info">Auto-refresh every 2s via WebSocket</div>

<script>
const grid = document.getElementById('agent-grid');
const msgList = document.getElementById('msg-list');
const prefixEl = document.getElementById('prefix');
const countEl = document.getElementById('agent-count');
const messages = [];
const MAX_MSGS = 50;

function ageSince(ts) {
  if (!ts) return '?';
  const s = Math.floor(Date.now()/1000) - ts;
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm';
  return Math.floor(s/3600) + 'h';
}

function renderAgents(agents) {
  countEl.textContent = agents.length + ' agents';
  grid.innerHTML = agents.map(a => {
    const age = Math.floor(Date.now()/1000) - a.last_seen;
    const stale = age > 30 ? 'stale' : '';
    const cls = a.status || 'unknown';
    return `<div class="card ${stale}">
      <div class="card-header">
        <span class="agent-id">${a.id}</span>
        <span class="status ${cls}">${a.status}</span>
      </div>
      <div class="card-body">
        <div class="row"><span class="label">Queue</span><span class="value">${a.queue_size || 0}</span></div>
        <div class="row"><span class="label">Tasks</span><span class="value">${a.tasks_completed || 0}</span></div>
        <div class="row"><span class="label">Mode</span><span class="value">${a.mode || '-'}</span></div>
        <div class="row"><span class="label">Last seen</span><span class="value">${ageSince(a.last_seen)} ago</span></div>
      </div>
    </div>`;
  }).join('');
}

function addMessage(agentId, data) {
  const text = data.response || data.prompt || JSON.stringify(data);
  const short = text.length > 120 ? text.slice(0,120) + '...' : text;
  messages.unshift({agent: agentId, text: short, time: new Date().toLocaleTimeString()});
  if (messages.length > MAX_MSGS) messages.length = MAX_MSGS;
  msgList.innerHTML = messages.map(m =>
    `<div class="msg"><span class="from">[${m.agent}]</span> ${m.text} <span class="time">${m.time}</span></div>`
  ).join('');
}

// Fetch initial
// Base path detection (works behind /inception/ proxy or standalone)
const basePath = location.pathname.replace(/\\/+$/, '');
const apiBase = basePath + '/api';
const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsBase = wsProto + '//' + location.host + basePath + '/ws';

fetch(apiBase + '/agents').then(r=>r.json()).then(d => {
  renderAgents(d.agents);
  if (d.agents.length > 0) {
    fetch(apiBase + '/health').then(r=>r.json()).then(h => prefixEl.textContent = 'live');
  }
});

// Status WebSocket
const wsStatus = new WebSocket(wsBase + '/status');
wsStatus.onmessage = (e) => {
  const d = JSON.parse(e.data);
  if (d.agents) renderAgents(d.agents);
};
wsStatus.onclose = () => setTimeout(() => location.reload(), 3000);

// Messages WebSocket
const wsMsg = new WebSocket(wsBase + '/messages');
wsMsg.onmessage = (e) => {
  const d = JSON.parse(e.data);
  if (d.agent_id && d.data) addMessage(d.agent_id, d.data);
};
</script>
</body>
</html>"""


# === Routes ===

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Inline dashboard UI"""
    return DASHBOARD_HTML


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


@app.get("/api/agents")
async def list_agents():
    """List all agents with their status"""
    if not redis_pool:
        raise HTTPException(status_code=503, detail="Redis not available")

    agents = []

    # Scan for agent status keys
    cursor = 0
    while True:
        cursor, keys = await redis_pool.scan(cursor, match=f"{MA_PREFIX}:agent:*", count=100)
        for key in keys:
            # Only process status hashes (ma:agent:{id} without :inbox/:outbox)
            parts = key.split(":")
            if len(parts) == 3 and parts[2].isdigit():
                agent_id = parts[2]
                data = await redis_pool.hgetall(key)
                agents.append(AgentStatus(
                    id=agent_id,
                    status=data.get("status", "unknown"),
                    last_seen=int(data.get("last_seen", 0)),
                    queue_size=int(data.get("queue_size", 0)),
                    tasks_completed=int(data.get("tasks_completed", 0)),
                    mode=data.get("mode", "unknown")
                ))
        if cursor == 0:
            break

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


@app.post("/api/agent/{agent_id}/send")
async def send_to_agent(agent_id: str, msg: SendMessage):
    """Send message to an agent"""
    if not redis_pool:
        raise HTTPException(status_code=503, detail="Redis not available")

    # Use legacy inbox format (RPUSH to list)
    inbox = f"{MA_PREFIX}:inject:{agent_id}"
    message = f"FROM:{msg.from_agent}|{msg.message}"

    await redis_pool.rpush(inbox, message)

    return {
        "status": "sent",
        "agent_id": agent_id,
        "message_length": len(msg.message),
        "timestamp": int(time.time())
    }


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

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for agent status updates (polling)"""
    await websocket.accept()

    try:
        while True:
            if redis_pool:
                # Get all agent statuses
                agents = []
                cursor = 0
                while True:
                    cursor, keys = await redis_pool.scan(cursor, match=f"{MA_PREFIX}:agent:*", count=100)
                    for key in keys:
                        parts = key.split(":")
                        if len(parts) == 3 and parts[2].isdigit():
                            agent_id = parts[2]
                            data = await redis_pool.hgetall(key)
                            agents.append({
                                "id": agent_id,
                                "status": data.get("status", "unknown"),
                                "last_seen": int(data.get("last_seen", 0)),
                            })
                    if cursor == 0:
                        break

                agents.sort(key=lambda a: int(a["id"]))

                await websocket.send_json({
                    "type": "status_update",
                    "agents": agents,
                    "timestamp": int(time.time())
                })

            await asyncio.sleep(2)  # Update every 2 seconds

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Status WebSocket error: {e}")


# === Main ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
