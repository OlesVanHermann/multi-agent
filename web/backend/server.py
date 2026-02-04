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
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis.asyncio as redis

# Config
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

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


@app.get("/api/agents")
async def list_agents():
    """List all agents with their status"""
    if not redis_pool:
        raise HTTPException(status_code=503, detail="Redis not available")

    agents = []

    # Scan for agent status keys
    cursor = 0
    while True:
        cursor, keys = await redis_pool.scan(cursor, match="ma:agent:*", count=100)
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

    key = f"ma:agent:{agent_id}"
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
    inbox = f"ma:inject:{agent_id}"
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
                cursor, keys = await redis_pool.scan(cursor, match="ma:agent:*:outbox", count=100)
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
                    cursor, keys = await redis_pool.scan(cursor, match="ma:agent:*", count=100)
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
