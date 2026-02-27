#!/usr/bin/env python3
"""
agent-tmux.py - Agent bridge using tmux to communicate with interactive Claude

EF-001 : Health endpoint HTTP (http.server stdlib, port 9100+id)
EF-003 : Heartbeat enrichi (10s, 7 champs, psutil CT-011)
R-INTEGRATE : MetricsCollector intégré (record_task_start/end/error/message)
CT-001 : http.server stdlib pour health endpoint
CT-002 : Préfixe mi: pour streams monitoring
CT-009 : XTRIM MAXLEN ~1000 sur streams heartbeat
CT-011 : psutil >= 5.9 pour EF-003

Usage: python agent-tmux.py <AGENT_ID>
Requires: tmux session "agent-{id}" with Claude running interactively
"""

import sys
import os
import time
import subprocess
import re
import argparse
import json
import http.server
import threading
from datetime import datetime
from threading import Thread, Lock
from queue import Queue, Empty
from enum import Enum
from collections import deque
from pathlib import Path

try:
    import redis
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "redis", "-q"])
    import redis

# psutil conditionnel (CT-011: autorisé pour EF-003)
_PSUTIL_AVAILABLE = False
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    pass

# === CONFIG ===
BASE_DIR = Path(__file__).parent.parent.parent
LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
MA_PREFIX = os.environ.get("MA_PREFIX", "A")

# Préfixe dédié monitoring (CT-002: mi: pour streams monitoring)
MONITORING_PREFIX = os.environ.get("MONITORING_PREFIX", "mi")

MAX_HISTORY = 50
RESPONSE_TIMEOUT = int(os.environ.get("RESPONSE_TIMEOUT", 300))
POLL_INTERVAL = 1.0

# EF-003 : intervalle heartbeat enrichi (CA-004: toutes les 10s ± 2s)
HEARTBEAT_INTERVAL = 10

# EF-001 : port de base pour health endpoint (port = base + agent_id numérique)
HEALTH_PORT_BASE = int(os.environ.get("AGENT_HEALTH_PORT_BASE", 9100))

# Claude prompt markers (to detect end of response)
PROMPT_MARKERS = ['❯', '>', '$', '%']

# CT-009 : borne streams monitoring
STREAM_MAXLEN = 1000


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    """Health endpoint HTTP — EF-001, CT-001 (http.server stdlib).

    Retourne JSON avec 6 champs requis (CA-001: <500ms).
    """
    agent_ref = None  # Set by _start_health_server

    def do_GET(self):
        if self.path == '/health':
            agent = self.__class__.agent_ref
            if not agent:
                self.send_response(503)
                self.end_headers()
                return
            try:
                redis_ok = agent._redis_ping()
            except Exception:
                redis_ok = False
            data = {
                "status": "healthy" if redis_ok else "degraded",
                "agent_id": agent.agent_id,
                "uptime_seconds": int(time.time() - agent._start_time),
                "last_heartbeat_ts": getattr(agent, '_last_heartbeat_ts', 0),
                "redis_connected": redis_ok,
                "pty_active": agent._tmux_session_exists()
            }
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default http.server logging


class State(Enum):
    IDLE = "idle"
    BUSY = "busy"


class TmuxAgent:
    def __init__(self, agent_id):
        self.agent_id = str(agent_id)
        self.session_name = f"{MA_PREFIX}-agent-{agent_id}"
        self.state = State.IDLE
        self.state_lock = Lock()

        # EF-001: start time for uptime
        self._start_time = time.time()

        # EF-003: compteurs pour heartbeat enrichi
        self._messages_processed = 0
        self._last_message_ts = 0
        self._last_heartbeat_ts = 0

        # Tracking
        self.tasks_completed = 0
        self.messages_since_reload = 0
        self.last_output_lines = 0

        # Queue
        self.prompt_queue = Queue()
        self.current_task = None
        self.history = deque(maxlen=MAX_HISTORY)

        # Logging
        self.log_dir = Path(LOG_DIR) / self.agent_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.logfile = open(self.log_dir / f"bridge_{ts}.log", "a", buffering=1)

        self._log(f"=== TmuxAgent {agent_id} started ===")

        # Verify tmux session exists
        if not self._tmux_session_exists():
            self._log(f"ERROR: tmux session '{self.session_name}' not found!")
            self._log("Start Claude first with: ./scripts/agent.sh start " + agent_id)
            sys.exit(1)

        # Redis
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.inbox = f"{MA_PREFIX}:agent:{agent_id}:inbox"
        self.outbox = f"{MA_PREFIX}:agent:{agent_id}:outbox"

        try:
            self.redis.ping()
        except redis.ConnectionError:
            self._log(f"ERROR: Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
            sys.exit(1)

        # R-INTEGRATE: MetricsCollector pour tracking performance
        try:
            from monitoring.metrics_collector import MetricsCollector
            self.metrics = MetricsCollector(self.redis, prefix=MONITORING_PREFIX)
            self._log("MetricsCollector initialized (R-INTEGRATE)")
        except ImportError:
            self.metrics = None
            self._log("WARNING: monitoring.metrics_collector not available")

        # Get initial pane content to know baseline
        self.last_output_lines = self._get_pane_line_count()

        # Legacy inbox (ma:inject:{id} format used by prompts)
        self.legacy_inbox = f"{MA_PREFIX}:inject:{agent_id}"

        # Threads
        self.running = True
        self.threads = [
            Thread(target=self._listen_redis, daemon=True, name="redis_listener"),
            Thread(target=self._listen_legacy, daemon=True, name="legacy_listener"),
            Thread(target=self._process_queue, daemon=True, name="queue_processor"),
            Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat"),  # EF-003
        ]
        for t in self.threads:
            t.start()

        # EF-001: Start health endpoint HTTP server
        self._health_server = None
        self._start_health_server()

        self._set_redis_status()
        self._log(f"Listening: Redis={self.inbox} + {self.legacy_inbox}, tmux={self.session_name}")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}][{self.agent_id}] {msg}"
        print(line, flush=True)
        self.logfile.write(line + "\n")

    def _log_event(self, event_type, detail=""):
        """Append JSON event to logs/{agent_id}/events.jsonl"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        entry = json.dumps({"ts": ts, "type": event_type, "detail": detail})
        try:
            with open(self.log_dir / "events.jsonl", "a") as fh:
                fh.write(entry + "\n")
        except Exception as e:
            self._log(f"event log error: {e}")

    def _redis_ping(self):
        """Test connexion Redis — utilisé par health endpoint (EF-001)."""
        try:
            return self.redis.ping()
        except Exception:
            return False

    def _tmux_session_exists(self):
        """Check if tmux session exists"""
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            capture_output=True
        )
        return result.returncode == 0

    def _get_pane_line_count(self):
        """Get current number of lines in tmux pane 0"""
        target = f"{self.session_name}:0"
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True, text=True
        )
        return len(result.stdout.split('\n'))

    def _capture_pane(self, lines=100):
        """Capture tmux pane 0 content (where Claude runs)"""
        target = f"{self.session_name}:0"
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True
        )
        return result.stdout

    def _send_keys(self, text):
        """Send keys to tmux pane 0 (where Claude runs)"""
        target = f"{self.session_name}:0"

        subprocess.run(["tmux", "send-keys", "-t", target, "C-c"], capture_output=True)
        time.sleep(0.5)
        subprocess.run(["tmux", "send-keys", "-t", target, "C-u"], capture_output=True)
        time.sleep(0.5)

        subprocess.run(
            ["tmux", "send-keys", "-t", target, "-l", text],
            capture_output=True
        )
        time.sleep(1)

        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Escape"],
            capture_output=True
        )
        time.sleep(1)

        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            capture_output=True
        )

    def _wait_for_response(self, timeout=RESPONSE_TIMEOUT):
        """Wait for Claude to finish responding and return the output"""
        start_time = time.time()
        baseline = self._capture_pane(200)
        baseline_hash = hash(baseline)

        last_content = ""
        stable_count = 0
        response_started = False
        last_printed = 0

        while time.time() - start_time < timeout:
            time.sleep(POLL_INTERVAL)

            current = self._capture_pane(200)

            if current != last_content:
                last_content = current
                stable_count = 0
                if hash(current) != baseline_hash:
                    response_started = True

                current_lines = current.strip().split('\n')
                if len(current_lines) > last_printed:
                    for line in current_lines[last_printed:][-5:]:
                        if line.strip():
                            print(f"  {line}", flush=True)
                    last_printed = len(current_lines)
            else:
                stable_count += 1

            current_lines = current.strip().split('\n')
            last_line = current_lines[-1].strip() if current_lines else ""
            for marker in PROMPT_MARKERS:
                if last_line.endswith(marker) or last_line == marker:
                    if response_started and stable_count >= 2:
                        response = '\n'.join(current_lines[:-1]).strip()
                        return response

            if stable_count > 10 and response_started:
                response = '\n'.join(current_lines).strip()
                for marker in PROMPT_MARKERS:
                    if response.endswith(marker):
                        response = response[:-len(marker)].strip()
                return response

        self._log("WARNING: Response timeout")
        return self._capture_pane(100)

    def _run_claude(self, prompt):
        """Send prompt to Claude via tmux and capture response"""
        self._log(f"Sending to Claude: {prompt[:60]}...")
        self._log_event("prompt", prompt[:120])

        print(f"\n{'─'*60}", flush=True)
        print(f"📤 CLAUDE (tmux interactive):", flush=True)
        print(f"{'─'*60}", flush=True)

        self._send_keys(prompt)
        response = self._wait_for_response()

        print(f"{'─'*60}\n", flush=True)

        return response

    def _set_redis_status(self):
        """Update status in Redis"""
        try:
            self.redis.hset(f"{MA_PREFIX}:agent:{self.agent_id}", mapping={
                "status": self.state.value,
                "last_seen": int(time.time()),
                "queue_size": self.prompt_queue.qsize(),
                "tasks_completed": self.tasks_completed,
                "messages_since_reload": self.messages_since_reload,
                "mode": "tmux-interactive"
            })
        except redis.ConnectionError:
            pass

    def _start_health_server(self):
        """Démarre le serveur HTTP health endpoint — EF-001, CT-001.

        Port = HEALTH_PORT_BASE + agent_id numérique (CA-001: configurable).
        """
        try:
            numeric_id = int(self.agent_id.split('-')[0])
        except (ValueError, IndexError):
            numeric_id = 0
        port = HEALTH_PORT_BASE + numeric_id

        handler_class = type('Handler', (_HealthHandler,), {'agent_ref': self})
        try:
            server = http.server.HTTPServer(('0.0.0.0', port), handler_class)
            server.timeout = 1
            self._health_server = server
            t = Thread(target=self._health_serve_loop, daemon=True, name="health_server")
            t.start()
            self._log(f"Health endpoint started on port {port} (EF-001)")
        except OSError as e:
            self._log(f"WARNING: Health server port {port} unavailable: {e}")

    def _health_serve_loop(self):
        """Boucle du serveur health — EF-001."""
        while self.running and self._health_server:
            try:
                self._health_server.handle_request()
            except Exception:
                pass

    def _heartbeat_loop(self):
        """Thread: heartbeat enrichi toutes les 10s — EF-003, CA-004.

        Publie 7 champs sur mi:agent:{id}:heartbeat (CT-002, CT-009).
        Champs: agent_id, timestamp, status, memory_mb, cpu_percent,
                messages_processed, last_message_ts.
        """
        while self.running:
            try:
                data = {
                    "agent_id": self.agent_id,
                    "timestamp": str(int(time.time())),
                    "status": self.state.value,
                    "messages_processed": str(self._messages_processed),
                    "last_message_ts": str(self._last_message_ts),
                }
                # psutil metrics (CT-011)
                if _PSUTIL_AVAILABLE:
                    proc = psutil.Process()
                    data["memory_mb"] = str(round(proc.memory_info().rss / 1048576, 1))
                    data["cpu_percent"] = str(proc.cpu_percent(interval=0))
                else:
                    data["memory_mb"] = "0"
                    data["cpu_percent"] = "0"

                # Publier heartbeat enrichi (CT-002: mi: prefix, CT-009: XTRIM)
                self.redis.xadd(
                    f"{MONITORING_PREFIX}:agent:{self.agent_id}:heartbeat",
                    data,
                    maxlen=STREAM_MAXLEN, approximate=True
                )
                self._last_heartbeat_ts = int(time.time())

                # Enregistrer dans métriques (R-INTEGRATE)
                if self.metrics:
                    self.metrics.record_heartbeat(self.agent_id, data)

            except redis.ConnectionError:
                self._log("Heartbeat: Redis connection lost")
            except Exception as e:
                self._log(f"Heartbeat error: {e}")

            time.sleep(HEARTBEAT_INTERVAL)

    def _listen_redis(self):
        """Thread: listen to Redis inbox (Streams format)"""
        last_id = '$'
        while self.running:
            try:
                result = self.redis.xread({self.inbox: last_id}, block=2000, count=1)
                if result:
                    stream, messages = result[0]
                    for msg_id, data in messages:
                        last_id = msg_id

                        # R-INTEGRATE: record inbound message
                        if self.metrics:
                            self.metrics.record_message(self.agent_id, "inbound")

                        msg_type = data.get('type', 'prompt')

                        if msg_type == 'prompt' or 'prompt' in data:
                            self.prompt_queue.put({
                                'prompt': data.get('prompt', ''),
                                'from_agent': data.get('from_agent', 'unknown'),
                                'msg_id': msg_id,
                                'source': 'redis'
                            })
                            self._log(f"<- Queued from {data.get('from_agent', '?')}: {data.get('prompt', '')[:50]}...")
                        elif msg_type == 'reload_prompt':
                            self._log("Received reload_prompt — reloading agent personality")
                            self._reload_prompt()
                        elif msg_type == 'response':
                            from_id = data.get('from_agent', '?')
                            response_text = data.get('response', '')
                            chunk_info = data.get('chunk', '')
                            is_complete = data.get('complete', 'true')

                            self._log(f"<- Response from {from_id} ({len(response_text)} chars){' ['+chunk_info+']' if chunk_info else ''}")

                            header = f"[FROM {from_id}]"
                            if chunk_info:
                                header += f" [{chunk_info}]"

                            notification = f"{header}\n{response_text}\n[/{from_id}]"
                            self.prompt_queue.put({
                                'prompt': notification,
                                'from_agent': f'response_{from_id}',
                                'msg_id': f"response-{int(time.time())}",
                                'source': 'response'
                            })
            except redis.ConnectionError:
                self._log("Redis connection lost, reconnecting...")
                time.sleep(2)
            except Exception as e:
                self._log(f"Redis error: {e}")
                # R-INTEGRATE: record error
                if self.metrics:
                    self.metrics.record_error(self.agent_id, type(e).__name__, str(e)[:200])
                time.sleep(1)

    def _listen_legacy(self):
        """Thread: listen to legacy Redis inbox (List format: ma:inject:{id})

        Supports FROM:xxx| prefix to identify sender:
          RPUSH ma:inject:300 "FROM:100|do something"
        """
        while self.running:
            try:
                result = self.redis.blpop(self.legacy_inbox, timeout=2)
                if result:
                    _, message = result

                    # R-INTEGRATE: record inbound message
                    if self.metrics:
                        self.metrics.record_message(self.agent_id, "inbound")

                    from_agent = 'legacy'
                    prompt = message
                    if message.startswith('FROM:'):
                        parts = message.split('|', 1)
                        if len(parts) == 2:
                            from_agent = parts[0][5:]
                            prompt = parts[1]

                    self.prompt_queue.put({
                        'prompt': prompt,
                        'from_agent': from_agent,
                        'msg_id': f"legacy-{int(time.time())}",
                        'source': 'legacy'
                    })
                    self._log(f"<- Queued from {from_agent}: {prompt[:50]}...")
            except redis.ConnectionError:
                time.sleep(2)
            except Exception as e:
                self._log(f"Legacy Redis error: {e}")
                if self.metrics:
                    self.metrics.record_error(self.agent_id, type(e).__name__, str(e)[:200])
                time.sleep(1)

    def _process_queue(self):
        """Thread: process prompt queue"""
        while self.running:
            try:
                task = self.prompt_queue.get(timeout=1)
            except Empty:
                continue

            with self.state_lock:
                self.state = State.BUSY
                self.current_task = task

            self._set_redis_status()
            src = f"[{task.get('from_agent', 'local')}]"
            self._log(f"-> Executing {src}: {task['prompt'][:80]}...")

            # R-INTEGRATE: record task start
            if self.metrics:
                self.metrics.record_task_start(self.agent_id, task_id=task.get('msg_id'))

            # Run prompt
            try:
                response = self._run_claude(task['prompt'])
            except Exception as e:
                self._log(f"ERROR running Claude: {e}")
                if self.metrics:
                    self.metrics.record_error(self.agent_id, type(e).__name__, str(e)[:200])
                response = f"[ERROR] {e}"

            # R-INTEGRATE: record task end
            if self.metrics:
                self.metrics.record_task_end(self.agent_id, task_id=task.get('msg_id'))

            # Save to history
            self.history.append({
                'prompt': task['prompt'],
                'response': response,
                'from_agent': task.get('from_agent'),
                'timestamp': int(time.time())
            })

            # Publish to Redis
            msg_data = {
                'response': response,
                'from_agent': self.agent_id,
                'to_agent': task.get('from_agent', ''),
                'timestamp': int(time.time()),
                'chars': len(response)
            }
            self.redis.xadd(self.outbox, msg_data)

            # R-INTEGRATE: record outbound message
            if self.metrics:
                self.metrics.record_message(self.agent_id, "outbound")

            # EF-003: update message counters
            self._messages_processed += 1
            self._last_message_ts = int(time.time())

            # Notify sender if it was another agent
            from_agent = task.get('from_agent')

            if from_agent and from_agent not in ['manual', 'cli', 'auto_init', 'unknown', 'legacy', 'compaction_reload']:
                try:
                    MAX_CHUNK = 15000

                    if len(response) <= MAX_CHUNK:
                        self.redis.xadd(f"{MA_PREFIX}:agent:{from_agent}:inbox", {
                            'response': response,
                            'from_agent': self.agent_id,
                            'type': 'response',
                            'timestamp': int(time.time()),
                            'complete': 'true'
                        })
                    else:
                        chunks = [response[i:i+MAX_CHUNK] for i in range(0, len(response), MAX_CHUNK)]
                        for i, chunk in enumerate(chunks):
                            self.redis.xadd(f"{MA_PREFIX}:agent:{from_agent}:inbox", {
                                'response': chunk,
                                'from_agent': self.agent_id,
                                'type': 'response',
                                'timestamp': int(time.time()),
                                'chunk': f"{i+1}/{len(chunks)}",
                                'complete': 'true' if i == len(chunks)-1 else 'false'
                            })

                    self._log(f"-> Full response sent to {from_agent} ({len(response)} chars)")
                except Exception as e:
                    self._log(f"Failed to send response to {from_agent}: {e}")
                    if self.metrics:
                        self.metrics.record_error(self.agent_id, "SendError", str(e)[:200])

            self._log(f"Response sent ({len(response)} chars)")
            self.tasks_completed += 1
            self.messages_since_reload += 1

            with self.state_lock:
                self.current_task = None
                self.state = State.IDLE

            self._set_redis_status()

    def send_to_agent(self, to_agent, prompt):
        """Send message to another agent"""
        if to_agent == 'all':
            agent_keys = self.redis.keys(f'{MA_PREFIX}:agent:*')
            sent_count = 0
            for key in agent_keys:
                parts = key.split(':')
                if len(parts) == 3 and parts[2].isdigit():
                    target_id = parts[2]
                    if target_id != self.agent_id:
                        self.redis.xadd(f"{MA_PREFIX}:agent:{target_id}:inbox", {
                            'prompt': prompt,
                            'from_agent': self.agent_id,
                            'timestamp': int(time.time())
                        })
                        sent_count += 1
            self._log(f"-> Broadcast to {sent_count} agents: {prompt[:60]}...")
        else:
            self.redis.xadd(f"{MA_PREFIX}:agent:{to_agent}:inbox", {
                'prompt': prompt,
                'from_agent': self.agent_id,
                'timestamp': int(time.time())
            })
            self._log(f"-> Sent to agent {to_agent}: {prompt[:60]}...")

    def run(self):
        """Main loop - also accepts stdin commands"""
        self._log("Ready. Monitoring Redis and stdin...")

        # Auto-load prompt
        prompt_path = self._find_prompt_file()
        if prompt_path:
            if self._is_x45_agent(prompt_path):
                files_list = self._get_x45_files(prompt_path)

                if files_list:
                    files_str = ", ".join(files_list)
                    self._log(f"Auto-loading x45 agent: {prompt_path} ({len(files_list)} files)")
                    self.prompt_queue.put({
                        'prompt': f"Lis ces fichiers dans l'ordre et deviens cet agent : {files_str}",
                        'from_agent': 'auto_init',
                        'msg_id': f"init_{int(time.time())}",
                    })
                else:
                    self._log(f"WARNING: x45 dir {prompt_path} found but no system.md or {self.agent_id}-system.md")
            else:
                self._log(f"Auto-loading: {prompt_path}")
                self.prompt_queue.put({
                    'prompt': f"deviens agent {prompt_path}",
                    'from_agent': 'auto_init',
                    'msg_id': f"init_{int(time.time())}",
                })

        try:
            import select
            while self.running:
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line:
                        if line.startswith('/'):
                            self._handle_command(line)
                        else:
                            self.prompt_queue.put({
                                'prompt': line,
                                'from_agent': 'manual',
                                'msg_id': f"manual-{int(time.time())}",
                            })
        except KeyboardInterrupt:
            self._log("Shutting down...")
        finally:
            self.running = False
            self.redis.hset(f"{MA_PREFIX}:agent:{self.agent_id}", "status", "stopped")
            if self._health_server:
                self._health_server.server_close()
            self.logfile.close()

    def _reload_prompt(self):
        """Reload agent prompt file to restore personality after context compaction"""
        prompt_path = self._find_prompt_file()
        if prompt_path:
            self._log(f"RELOAD: {prompt_path} (with /reset to clear thinking blocks)")
            self.messages_since_reload = 0

            self._send_keys("/reset")
            time.sleep(2)

            if self._is_x45_agent(prompt_path):
                files_list = self._get_x45_files(prompt_path)
                if files_list:
                    files_str = ", ".join(files_list)
                    self.prompt_queue.put({
                        'prompt': f"Lis ces fichiers dans l'ordre et deviens cet agent : {files_str}",
                        'from_agent': 'compaction_reload',
                        'msg_id': f"reload_{int(time.time())}",
                    })
            else:
                self.prompt_queue.put({
                    'prompt': f"deviens agent {prompt_path}",
                    'from_agent': 'compaction_reload',
                    'msg_id': f"reload_{int(time.time())}",
                })
            self._set_redis_status()

    def _resolve_prompts_dir(self, prompts_dir, numeric_id):
        """Resolve a numeric ID to its prompts directory.

        Handles both plain (341/) and verbose (341-analyse-archi-.../) names.
        R-REGTEST: guard against missing prompts_dir.
        """
        exact = prompts_dir / numeric_id
        if exact.is_dir():
            return exact
        if not prompts_dir.is_dir():
            return None
        for d in prompts_dir.iterdir():
            if d.is_dir() and re.match(rf'^{re.escape(numeric_id)}-', d.name):
                return d
        return None

    def _find_prompt_file(self):
        """Find prompt file for this agent.

        Supports three formats:
        - x45 triangles (new): prompts/{dir}/{id}.md symlink
        - x45 mode (old): prompts/{id}/system.md (directory with 3 files)
        - Pipeline standard: prompts/{id}-*.md (flat file)
        """
        prompts_dir = BASE_DIR / "prompts"

        parent_id = self.agent_id.split('-')[0] if '-' in self.agent_id else self.agent_id

        parent_dir = self._resolve_prompts_dir(prompts_dir, parent_id)

        if parent_dir:
            x45_entry = parent_dir / f"{self.agent_id}.md"
            if x45_entry.exists():
                return str(x45_entry)

            x45_system = parent_dir / f"{self.agent_id}-system.md"
            if x45_system.exists():
                return str(parent_dir)

            system_md = parent_dir / "system.md"
            if system_md.exists():
                return str(parent_dir)

        if '-' in self.agent_id and parent_dir:
            sat_system = parent_dir / f"{self.agent_id}-system.md"
            if sat_system.exists():
                return str(parent_dir)

        pattern = f"{self.agent_id}-*.md"
        matches = [m for m in prompts_dir.glob(pattern) if m.is_file()]
        if matches:
            return str(matches[0])
        return None

    def _is_x45_agent(self, prompt_path):
        """Check if prompt_path is an x45 directory (vs .md file)."""
        return Path(prompt_path).is_dir()

    def _get_x45_files(self, prompt_path):
        """Get the ordered list of x45 files to load for this agent."""
        p = Path(prompt_path)
        aid = self.agent_id
        files_list = []

        for candidate in [p / f"{aid}.md", p.parent / "AGENT.md", p / "AGENT.md"]:
            if candidate.exists():
                files_list.append(str(candidate))
                break

        for candidate in [p / f"{aid}-system.md", p / "system.md"]:
            if candidate.exists():
                files_list.append(str(candidate))
                break

        for candidate in [p / f"{aid}-memory.md", p / "memory.md"]:
            if candidate.exists():
                files_list.append(str(candidate))
                break

        for candidate in [p / f"{aid}-methodology.md", p / "methodology.md"]:
            if candidate.exists():
                files_list.append(str(candidate))
                break

        return files_list

    def _handle_command(self, line):
        """Handle slash commands"""
        if line == '/status':
            self._log(f"State: {self.state.value} | Queue: {self.prompt_queue.qsize()} | Tasks: {self.tasks_completed}")
        elif line == '/queue':
            self._log(f"Queue size: {self.prompt_queue.qsize()}")
        elif line.startswith('/send '):
            parts = line[6:].split(' ', 1)
            if len(parts) == 2:
                self.send_to_agent(parts[0], parts[1])
            else:
                self._log("Usage: /send <agent_id> <message>")
        elif line == '/help':
            self._log("Commands: /status /queue /send <id> <msg> /help")
        else:
            self._log(f"Unknown command: {line}")


def main():
    parser = argparse.ArgumentParser(description='TmuxAgent - Bridge for interactive Claude in tmux')
    parser.add_argument('agent_id', help='Agent ID (e.g., 300)')
    args = parser.parse_args()

    agent = TmuxAgent(args.agent_id)
    agent.run()


if __name__ == "__main__":
    main()
