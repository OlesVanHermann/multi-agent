"""
Multi-Agent Dashboard

Layout:
┌──────────┬────────────────────────────────────┐
│          │  SUPER-MASTER (30%)                │
│  Agents  ├────────────────────────────────────┤
│  List    │  MASTER (30%)                      │
│          ├────────────────────────────────────┤
│ (click   │  SLAVES (40%) - scrollable         │
│  to      │  ┌─slave-01─┐ ┌─slave-02─┐        │
│  scroll) │  │          │ │          │        │
│          │  └──────────┘ └──────────┘        │
└──────────┴────────────────────────────────────┘
"""

import os
import json
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import redis

app = FastAPI(title="Multi-Agent")

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
MA_PREFIX = os.environ.get("MA_PREFIX", "ma")

def get_redis():
    if "://" in REDIS_URL:
        hp = REDIS_URL.split("://")[1]
        host, port = (hp.split(":") + ["6379"])[:2]
        return redis.Redis(host=host, port=int(port), decode_responses=True)
    return redis.Redis(decode_responses=True)


DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Agent</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
            background: #0d1117; 
            color: #c9d1d9;
            height: 100vh;
            overflow: hidden;
        }
        
        .container { display: flex; height: 100vh; }
        
        /* Sidebar */
        .sidebar {
            width: 180px;
            background: #161b22;
            border-right: 1px solid #30363d;
            display: flex;
            flex-direction: column;
        }
        .sidebar-header {
            padding: 12px;
            border-bottom: 1px solid #30363d;
            font-weight: bold;
            color: #58a6ff;
            font-size: 14px;
        }
        .sidebar-section {
            padding: 8px;
            font-size: 11px;
            color: #8b949e;
            text-transform: uppercase;
            border-bottom: 1px solid #21262d;
        }
        .agent-list {
            flex: 1;
            overflow-y: auto;
            padding: 5px;
        }
        .agent-item {
            padding: 6px 10px;
            margin: 2px 0;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .agent-item:hover { background: #21262d; }
        .agent-item.active { background: #1f6feb33; }
        .status-dot {
            width: 6px; height: 6px;
            border-radius: 50%;
            background: #484f58;
            flex-shrink: 0;
        }
        .status-dot.idle { background: #3fb950; }
        .status-dot.busy { background: #f0883e; }
        .status-dot.error { background: #f85149; }
        
        /* Panels */
        .panels {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
        }
        
        .panel {
            display: flex;
            flex-direction: column;
            border-bottom: 1px solid #30363d;
            min-height: 0;
        }
        .panel.top { flex: 0 0 30%; }
        .panel.middle { flex: 0 0 30%; }
        .panel.bottom { flex: 1; }
        
        .panel-header {
            padding: 8px 12px;
            background: #161b22;
            border-bottom: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        .panel-title {
            font-weight: bold;
            font-size: 11px;
            text-transform: uppercase;
        }
        .panel-title.super-master { color: #f0883e; }
        .panel-title.master { color: #a371f7; }
        .panel-title.slave { color: #3fb950; }
        .panel-status { font-size: 10px; color: #8b949e; }
        
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 8px 12px;
            font-size: 12px;
        }
        .message {
            margin: 4px 0;
            padding: 6px 8px;
            border-radius: 4px;
        }
        .message.user { background: #1f6feb22; border-left: 2px solid #1f6feb; }
        .message.assistant { background: #23863622; border-left: 2px solid #238636; }
        .message.system { background: #21262d; font-size: 10px; color: #8b949e; }
        .message-header { font-size: 9px; color: #8b949e; margin-bottom: 2px; }
        .message-content {
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 80px;
            overflow-y: auto;
        }
        
        .input-area {
            padding: 6px 12px;
            background: #161b22;
            display: flex;
            gap: 6px;
            flex-shrink: 0;
        }
        .input-area input {
            flex: 1;
            background: #0d1117;
            border: 1px solid #30363d;
            color: #c9d1d9;
            padding: 6px 10px;
            border-radius: 4px;
            font-family: inherit;
            font-size: 12px;
        }
        .input-area input:focus { outline: none; border-color: #1f6feb; }
        .input-area button {
            background: #238636;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 11px;
        }
        .input-area button:hover { background: #2ea043; }
        
        /* Slaves grid */
        .slaves-container {
            flex: 1;
            overflow-y: auto;
            padding: 10px;
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-content: flex-start;
        }
        .slave-card {
            width: calc(50% - 5px);
            min-width: 300px;
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            display: flex;
            flex-direction: column;
            max-height: 250px;
        }
        .slave-card.highlighted {
            border-color: #3fb950;
            box-shadow: 0 0 10px #3fb95033;
        }
        .slave-card .panel-header {
            padding: 6px 10px;
        }
        .slave-card .messages {
            flex: 1;
            min-height: 100px;
            max-height: 150px;
        }
        .slave-card .input-area {
            padding: 4px 8px;
        }
        .slave-card .input-area input {
            padding: 4px 8px;
            font-size: 11px;
        }
        .slave-card .input-area button {
            padding: 4px 8px;
            font-size: 10px;
        }
        
        .empty-state {
            color: #484f58;
            text-align: center;
            padding: 15px;
            font-size: 11px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <div class="sidebar-header">🤖 Multi-Agent</div>
            <div class="sidebar-section">Hierarchy</div>
            <div class="agent-list">
                <div class="agent-item" onclick="scrollToPanel('super-master')">
                    <span class="status-dot" id="dot-super-master"></span>
                    <span>super-master</span>
                </div>
                <div class="agent-item" onclick="scrollToPanel('master')">
                    <span class="status-dot" id="dot-master"></span>
                    <span>master</span>
                </div>
            </div>
            <div class="sidebar-section">Slaves</div>
            <div class="agent-list" id="slave-list"></div>
        </div>
        
        <div class="panels">
            <!-- Super-Master -->
            <div class="panel top" id="panel-super-master">
                <div class="panel-header">
                    <span class="panel-title super-master">◆ Super-Master</span>
                    <span class="panel-status" id="status-super-master">--</span>
                </div>
                <div class="messages" id="messages-super-master">
                    <div class="empty-state">Waiting for super-master...</div>
                </div>
                <div class="input-area">
                    <input type="text" id="input-super-master" placeholder="Send...">
                    <button onclick="sendMessage('super-master')">Send</button>
                </div>
            </div>
            
            <!-- Master -->
            <div class="panel middle" id="panel-master">
                <div class="panel-header">
                    <span class="panel-title master">◆ Master</span>
                    <span class="panel-status" id="status-master">--</span>
                </div>
                <div class="messages" id="messages-master">
                    <div class="empty-state">Waiting for master...</div>
                </div>
                <div class="input-area">
                    <input type="text" id="input-master" placeholder="Send...">
                    <button onclick="sendMessage('master')">Send</button>
                </div>
            </div>
            
            <!-- Slaves -->
            <div class="panel bottom">
                <div class="panel-header">
                    <span class="panel-title slave">◆ Slaves</span>
                    <span class="panel-status" id="slave-count">0 slaves</span>
                </div>
                <div class="slaves-container" id="slaves-container">
                    <div class="empty-state" style="width:100%">No slaves running</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let agents = {};
        let websockets = {};
        let slaveCards = {};
        
        async function refreshAgents() {
            try {
                const resp = await fetch('/api/agents');
                agents = await resp.json();
                updateUI();
            } catch (e) {}
        }
        
        function updateUI() {
            const slaves = [];
            
            for (const [id, dataStr] of Object.entries(agents)) {
                const data = JSON.parse(dataStr);
                
                if (data.role === 'super-master') {
                    document.getElementById('dot-super-master').className = `status-dot ${data.status}`;
                    document.getElementById('status-super-master').textContent = data.status;
                    connectWS('super-master', 'super-master');
                }
                else if (data.role === 'master') {
                    document.getElementById('dot-master').className = `status-dot ${data.status}`;
                    document.getElementById('status-master').textContent = data.status;
                    connectWS('master', 'master');
                }
                else {
                    slaves.push({ id, data });
                }
            }
            
            // Update slave list in sidebar
            const slaveList = document.getElementById('slave-list');
            slaveList.innerHTML = slaves.map(s => `
                <div class="agent-item" onclick="scrollToSlave('${s.id}')">
                    <span class="status-dot ${s.data.status}"></span>
                    <span>${s.id}</span>
                </div>
            `).join('') || '<div class="empty-state">No slaves</div>';
            
            document.getElementById('slave-count').textContent = `${slaves.length} slaves`;
            
            // Update slave cards
            updateSlaveCards(slaves);
        }
        
        function updateSlaveCards(slaves) {
            const container = document.getElementById('slaves-container');
            
            // Remove old slaves
            const currentIds = new Set(slaves.map(s => s.id));
            for (const id of Object.keys(slaveCards)) {
                if (!currentIds.has(id)) {
                    slaveCards[id].remove();
                    delete slaveCards[id];
                    if (websockets[`slave-${id}`]) {
                        websockets[`slave-${id}`].close();
                        delete websockets[`slave-${id}`];
                    }
                }
            }
            
            // Add/update slaves
            for (const { id, data } of slaves) {
                if (!slaveCards[id]) {
                    // Create new card
                    const card = document.createElement('div');
                    card.className = 'slave-card';
                    card.id = `slave-card-${id}`;
                    card.innerHTML = `
                        <div class="panel-header">
                            <span class="panel-title slave">● ${id}</span>
                            <span class="panel-status" id="status-slave-${id}">${data.status}</span>
                        </div>
                        <div class="messages" id="messages-slave-${id}">
                            <div class="empty-state">Loading...</div>
                        </div>
                        <div class="input-area">
                            <input type="text" id="input-slave-${id}" placeholder="Send...">
                            <button onclick="sendMessage('${id}')">Send</button>
                        </div>
                    `;
                    
                    // Enter key handler
                    card.querySelector('input').addEventListener('keypress', (e) => {
                        if (e.key === 'Enter') sendMessage(id);
                    });
                    
                    container.appendChild(card);
                    slaveCards[id] = card;
                    
                    // Connect WS and load history
                    connectWS(id, `slave-${id}`);
                    loadHistory(id, `slave-${id}`);
                } else {
                    // Update status
                    document.getElementById(`status-slave-${id}`).textContent = data.status;
                }
            }
            
            // Remove empty state if we have slaves
            if (slaves.length > 0) {
                const empty = container.querySelector('.empty-state');
                if (empty && !empty.closest('.slave-card')) empty.remove();
            }
        }
        
        function scrollToPanel(id) {
            document.getElementById(`panel-${id}`).scrollIntoView({ behavior: 'smooth' });
        }
        
        function scrollToSlave(id) {
            const card = document.getElementById(`slave-card-${id}`);
            if (card) {
                // Highlight briefly
                card.classList.add('highlighted');
                setTimeout(() => card.classList.remove('highlighted'), 2000);
                
                card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
        
        function connectWS(agentId, key) {
            if (websockets[key]) return; // Already connected
            
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${protocol}//${location.host}/ws/conversation/${agentId}`);
            
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                appendMessage(key, msg);
            };
            
            ws.onclose = () => {
                delete websockets[key];
                setTimeout(() => connectWS(agentId, key), 3000);
            };
            
            websockets[key] = ws;
        }
        
        async function loadHistory(agentId, key) {
            try {
                const resp = await fetch(`/api/conversation/${agentId}?limit=30`);
                const messages = await resp.json();
                
                const containerId = key === 'super-master' ? 'messages-super-master' :
                                   key === 'master' ? 'messages-master' :
                                   `messages-slave-${agentId}`;
                const container = document.getElementById(containerId);
                if (!container) return;
                
                container.innerHTML = '';
                for (const msg of messages) {
                    appendMessage(key, msg);
                }
                container.scrollTop = container.scrollHeight;
            } catch (e) {}
        }
        
        function appendMessage(key, msg) {
            const containerId = key === 'super-master' ? 'messages-super-master' :
                               key === 'master' ? 'messages-master' :
                               `messages-${key}`;
            const container = document.getElementById(containerId);
            if (!container) return;
            
            const empty = container.querySelector('.empty-state');
            if (empty) empty.remove();
            
            const div = document.createElement('div');
            div.className = `message ${msg.role}`;
            
            const time = msg.timestamp ? msg.timestamp.substring(11, 19) : '';
            let content = msg.content || '';
            if (content.length > 300) content = content.substring(0, 300) + '...';
            
            div.innerHTML = `
                <div class="message-header">${msg.role.toUpperCase()} · ${time}</div>
                <div class="message-content">${escapeHtml(content)}</div>
            `;
            
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        async function sendMessage(agentId) {
            const inputId = agentId === 'super-master' ? 'input-super-master' :
                           agentId === 'master' ? 'input-master' :
                           `input-slave-${agentId}`;
            const input = document.getElementById(inputId);
            if (!input) return;
            
            const message = input.value.trim();
            if (!message) return;
            
            try {
                await fetch(`/api/inject/${agentId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message })
                });
                input.value = '';
            } catch (e) {}
        }
        
        // Enter handlers for main panels
        ['super-master', 'master'].forEach(id => {
            document.getElementById(`input-${id}`).addEventListener('keypress', (e) => {
                if (e.key === 'Enter') sendMessage(id);
            });
        });
        
        // Init
        refreshAgents();
        loadHistory('super-master', 'super-master');
        loadHistory('master', 'master');
        setInterval(refreshAgents, 3000);
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


@app.get("/api/agents")
async def get_agents():
    r = get_redis()
    return r.hgetall(f"{MA_PREFIX}:agents")


@app.get("/api/conversation/{agent_id}")
async def get_conversation(agent_id: str, limit: int = 50):
    r = get_redis()
    messages = r.xrevrange(f"{MA_PREFIX}:conversation:{agent_id}", count=limit)
    return [{"id": m[0], "role": m[1].get("role",""), "content": m[1].get("content",""), "timestamp": m[1].get("timestamp","")} for m in reversed(messages)]


@app.post("/api/inject/{agent_id}")
async def inject_message(agent_id: str, payload: dict):
    r = get_redis()
    if msg := payload.get("message"):
        r.rpush(f"{MA_PREFIX}:inject:{agent_id}", msg)
    return {"ok": True}


@app.websocket("/ws/conversation/{agent_id}")
async def ws_conversation(websocket: WebSocket, agent_id: str):
    await websocket.accept()
    r = get_redis()
    pubsub = r.pubsub()
    pubsub.subscribe(f"{MA_PREFIX}:conversation:{agent_id}:live")
    try:
        while True:
            if msg := pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0):
                if msg['type'] == 'message':
                    await websocket.send_text(msg['data'])
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.close()


@app.get("/health")
async def health():
    try:
        get_redis().ping()
        return {"status": "ok"}
    except:
        return {"status": "error"}
