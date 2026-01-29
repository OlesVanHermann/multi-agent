#!/usr/bin/env python3
"""
agent.py - Agent unifié Redis Streams + Claude Code + Sessions
Usage: python agent.py <AGENT_ID> [--headless]

Combine:
- Redis Streams (XREAD/XADD) pour communication
- Sessions Claude (--session-id/--resume) pour prompt caching
- subprocess avec --print pour exécution fiable

États: IDLE → BUSY → IDLE
- IDLE: accepte nouveau prompt (Redis ou stdin)
- BUSY: exécute le prompt, nouveaux prompts en queue

Commandes interactives:
  /status      - Affiche l'état actuel
  /queue       - Taille de la queue
  /flush       - Vide la queue
  /send <id> <msg> - Envoie un message à un autre agent
  /history     - Derniers échanges
  /session     - Info session Claude
  /newsession  - Force nouvelle session
  Ctrl+C       - Quitter
"""

import sys
import os
import time
import select
import argparse
import uuid
import subprocess
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


# === CONFIG ===
BASE_DIR = Path(__file__).parent.parent.parent
LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

# Timing
HEARTBEAT_INTERVAL = 10   # secondes entre heartbeats
MAX_HISTORY = 50          # nombre d'échanges gardés en mémoire
CLAUDE_TIMEOUT = 300      # timeout pour Claude (5 min)

# Session management
SESSION_TASK_LIMIT = 50   # Reset session après N tâches


class State(Enum):
    IDLE = "idle"
    BUSY = "busy"


class Agent:
    def __init__(self, agent_id, headless=False, prompt_file=None):
        self.agent_id = str(agent_id)
        self.headless = headless
        self.state = State.IDLE
        self.state_lock = Lock()

        # Session management
        self.session_id = None
        self.session_initialized = False
        self.tasks_in_session = 0
        self.sessions_created = 0
        self.tasks_completed = 0

        # Queues et buffers
        self.prompt_queue = Queue()
        self.current_task = None
        self.history = deque(maxlen=MAX_HISTORY)

        # Setup log directory and file
        self.log_dir = Path(LOG_DIR) / self.agent_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.logfile = open(self.log_dir / f"agent_{ts}.log", "a", buffering=1)
        self._log(f"=== Agent {agent_id} started (headless={headless}) ===")

        # System prompt
        self.system_prompt = self._load_system_prompt(prompt_file)

        # Redis (Streams)
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.inbox = f"ma:agent:{agent_id}:inbox"
        self.outbox = f"ma:agent:{agent_id}:outbox"

        # Test connexion Redis
        try:
            self.redis.ping()
        except redis.ConnectionError:
            print(f"[ERROR] Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
            sys.exit(1)

        # Create new session
        self._new_session()

        # Threads
        self.running = True
        self.threads = [
            Thread(target=self._listen_redis, daemon=True, name="redis_listener"),
            Thread(target=self._heartbeat, daemon=True, name="heartbeat"),
            Thread(target=self._process_queue, daemon=True, name="queue_processor"),
        ]
        for t in self.threads:
            t.start()

        self._set_redis_status()
        self._log(f"Listening: Redis={self.inbox}, stdin={'disabled' if headless else 'enabled'}")
        self._log(f"Session: {self.session_id[:8]}...")

    def _load_system_prompt(self, prompt_file=None) -> str:
        """Load the agent's system prompt"""
        if prompt_file and Path(prompt_file).exists():
            content = Path(prompt_file).read_text()
            self._log(f"Loaded prompt: {prompt_file}")
            return content

        prompts_dir = BASE_DIR / "prompts"
        prompt_map = {
            "000": "000-mini-super.md",
            "100": "100-master.md",
            "200": "200-explorer.md",
            "201": "201-doc-generator.md",
            "300": "300-dev-excel.md",
            "301": "301-dev-word.md",
            "302": "302-dev-pptx.md",
            "303": "303-dev-pdf.md",
            "400": "400-merge.md",
            "500": "500-test.md",
            "501": "501-test-creator.md",
            "502": "502-test-mapper.md",
            "600": "600-release.md",
            "900": "900-architect.md",
        }

        filename = prompt_map.get(self.agent_id)
        if filename:
            path = prompts_dir / filename
            if path.exists():
                self._log(f"Loaded prompt: {filename}")
                return path.read_text()

        return f"You are Agent {self.agent_id}. Execute tasks as instructed."

    def _new_session(self):
        """Create a new Claude session"""
        self.session_id = str(uuid.uuid4())
        self.session_initialized = False
        self.tasks_in_session = 0
        self.sessions_created += 1
        self._log(f"New session #{self.sessions_created}: {self.session_id[:8]}")

    def _log(self, msg):
        """Log avec timestamp"""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}][{self.agent_id}] {msg}"
        print(line, flush=True)
        self.logfile.write(line + "\n")

    def _set_redis_status(self):
        """Publie l'état dans Redis"""
        try:
            pipe = self.redis.pipeline()
            pipe.hset(f"ma:agent:{self.agent_id}", mapping={
                "status": self.state.value,
                "last_seen": int(time.time()),
                "queue_size": self.prompt_queue.qsize(),
                "current_task_from": str(self.current_task.get('from_agent', '')) if self.current_task else '',
                "headless": str(self.headless),
                "session_id": self.session_id[:8] if self.session_id else '',
                "tasks_completed": self.tasks_completed,
                "tasks_in_session": self.tasks_in_session,
                "sessions_created": self.sessions_created,
            })
            pipe.expire(f"ma:agent:{self.agent_id}", 60)
            pipe.execute()
        except redis.ConnectionError:
            pass

    def _run_claude(self, prompt: str) -> str:
        """Execute Claude with subprocess and --print"""
        # Use CLAUDE_CMD env var if set, otherwise default to claude
        claude_cmd = os.environ.get("CLAUDE_CMD", "claude")
        cmd = [claude_cmd, "--dangerously-skip-permissions", "--print"]

        if not self.session_initialized:
            cmd.extend(["--session-id", self.session_id])
        else:
            cmd.extend(["--resume", self.session_id])

        # Pass prompt as argument (more reliable than stdin)
        cmd.append(prompt)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT
            )

            output = result.stdout.strip()

            if result.returncode != 0:
                error = result.stderr.strip()
                self._log(f"Claude error: {error[:100]}")
                if not output:
                    output = f"Error: {error}"

            return output

        except subprocess.TimeoutExpired:
            self._log("Claude timeout")
            return "Error: Timeout"
        except Exception as e:
            self._log(f"Claude exception: {e}")
            return f"Error: {e}"

    def _listen_redis(self):
        """Thread: écoute Redis inbox"""
        last_id = '$'
        while self.running:
            try:
                result = self.redis.xread({self.inbox: last_id}, block=2000, count=1)
                if result:
                    stream, messages = result[0]
                    for msg_id, data in messages:
                        last_id = msg_id
                        msg_type = data.get('type', 'prompt')

                        if msg_type == 'response':
                            self._log(f"<- Response from {data.get('from_agent')}: {data.get('response', '')[:100]}...")
                            self.history.append({
                                'type': 'received_response',
                                'from_agent': data.get('from_agent'),
                                'response': data.get('response', ''),
                                'timestamp': int(time.time())
                            })
                        else:
                            prompt = data.get('prompt', '').strip()
                            if prompt:
                                task = {
                                    'prompt': prompt,
                                    'from_agent': data.get('from_agent'),
                                    'msg_id': msg_id,
                                    'source': 'redis'
                                }
                                self.prompt_queue.put(task)
                                self._log(f"<- Queued from {data.get('from_agent', '?')}: {prompt[:60]}...")

            except redis.ConnectionError:
                self._log("Redis connection lost, retrying...")
                time.sleep(5)
            except Exception as e:
                self._log(f"Redis listener error: {e}")
                time.sleep(1)

    def _process_queue(self):
        """Thread: traite la queue de prompts"""
        while self.running:
            try:
                if self.state != State.IDLE:
                    time.sleep(0.5)
                    continue

                task = self.prompt_queue.get(timeout=1)
                self._execute_prompt(task)

            except Empty:
                continue
            except Exception as e:
                self._log(f"Queue processor error: {e}")

    def _execute_prompt(self, task):
        """Exécute un prompt via Claude"""
        with self.state_lock:
            if self.state != State.IDLE:
                self.prompt_queue.put(task)
                return

            self.state = State.BUSY
            self.current_task = task

        self._set_redis_status()
        src = f"[{task.get('from_agent', 'local')}]" if task.get('source') == 'redis' else "[manual]"
        self._log(f"-> Executing {src}: {task['prompt'][:80]}...")

        # Build prompt
        prompt = task['prompt']
        if not self.session_initialized:
            full_prompt = f"""{self.system_prompt}

---

## TACHE
{prompt}

EXECUTE MAINTENANT.
"""
        else:
            full_prompt = prompt

        # Execute
        response = self._run_claude(full_prompt)

        # Mark session as initialized
        if not self.session_initialized:
            self.session_initialized = True
            self._log("Session initialized (prompt cached)")

        # Save to history
        self.history.append({
            'type': 'exchange',
            'prompt': task.get('prompt', ''),
            'response': response,
            'from_agent': task.get('from_agent'),
            'timestamp': int(time.time())
        })

        # Publish response to Redis
        msg_data = {
            'response': response,
            'from_agent': self.agent_id,
            'to_agent': task.get('from_agent', ''),
            'in_reply_to': task.get('msg_id', ''),
            'timestamp': int(time.time()),
            'chars': len(response)
        }
        self.redis.xadd(self.outbox, msg_data)

        # Notify sender's inbox if it was another agent
        from_agent = task.get('from_agent')
        if from_agent and from_agent != 'manual' and from_agent != 'cli':
            try:
                self.redis.xadd(f"ma:agent:{from_agent}:inbox", {
                    'response': response[:4000],
                    'from_agent': self.agent_id,
                    'type': 'response',
                    'timestamp': int(time.time())
                })
            except:
                pass

        self._log(f"Response sent ({len(response)} chars)")
        self.tasks_completed += 1
        self.tasks_in_session += 1

        # Check session limit
        if self.tasks_in_session >= SESSION_TASK_LIMIT:
            self._log(f"Session task limit reached ({SESSION_TASK_LIMIT}), creating new session")
            self._new_session()

        # Reset state
        self.current_task = None
        self.state = State.IDLE
        self._set_redis_status()

    def _heartbeat(self):
        """Thread: heartbeat Redis"""
        while self.running:
            self._set_redis_status()
            time.sleep(HEARTBEAT_INTERVAL)

    def send_to_agent(self, to_agent, prompt):
        """Envoyer un message à un autre agent"""
        self.redis.xadd(f"ma:agent:{to_agent}:inbox", {
            'prompt': prompt,
            'from_agent': self.agent_id,
            'timestamp': int(time.time())
        })
        self._log(f"-> Sent to agent {to_agent}: {prompt[:60]}...")

    def manual_input(self, prompt):
        """Input manuel (stdin)"""
        task = {
            'prompt': prompt,
            'from_agent': 'manual',
            'msg_id': f"manual-{int(time.time())}",
            'source': 'manual'
        }

        if self.state == State.IDLE:
            self._execute_prompt(task)
        else:
            self.prompt_queue.put(task)
            self._log(f"Queued (agent busy): {prompt[:60]}...")

    def _handle_command(self, line):
        """Gère les commandes slash"""
        if line == '/status':
            self._log(f"State: {self.state.value} | Queue: {self.prompt_queue.qsize()} | Tasks: {self.tasks_completed}")
        elif line == '/queue':
            self._log(f"Queue size: {self.prompt_queue.qsize()}")
        elif line == '/flush':
            count = 0
            while not self.prompt_queue.empty():
                self.prompt_queue.get()
                count += 1
            self._log(f"Queue flushed ({count} items)")
        elif line == '/session':
            self._log(f"Session: {self.session_id[:8]} | Initialized: {self.session_initialized} | Tasks: {self.tasks_in_session}/{SESSION_TASK_LIMIT}")
        elif line == '/newsession':
            self._log("Creating new session...")
            self._new_session()
            self._log(f"New session ready: {self.session_id[:8]}")
        elif line == '/history':
            self._log(f"Last {len(self.history)} exchanges:")
            for h in list(self.history)[-5:]:
                if h['type'] == 'exchange':
                    self._log(f"  [{h.get('from_agent', 'manual')}] {h['prompt'][:50]}... -> {len(h['response'])} chars")
                else:
                    self._log(f"  <- Response from {h['from_agent']}: {h['response'][:50]}...")
        elif line.startswith('/send '):
            parts = line[6:].split(' ', 1)
            if len(parts) == 2:
                to_agent = parts[0]
                msg = parts[1]
                self.send_to_agent(to_agent, msg)
            else:
                self._log("Usage: /send <agent_id> <message>")
        elif line == '/help':
            self._log("Commands: /status /queue /flush /session /newsession /history /send <id> <msg> /help")
        else:
            self._log(f"Unknown command: {line}")

    def run_interactive(self):
        """Boucle principale avec stdin"""
        self._log("Ready. Type prompts or /help for commands.")

        try:
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
                            self.manual_input(line)
        except KeyboardInterrupt:
            self._log("Shutting down...")
        finally:
            self.shutdown()

    def run_headless(self):
        """Mode daemon sans stdin"""
        self._log("Running in headless mode. Ctrl+C to quit.")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self._log("Shutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        """Arrêt propre"""
        self.running = False
        self.redis.hset(f"ma:agent:{self.agent_id}", "status", "stopped")
        self.logfile.close()
        self._log(f"Agent stopped. Total: {self.tasks_completed} tasks, {self.sessions_created} sessions")


def main():
    parser = argparse.ArgumentParser(description='Multi-Agent Bridge for Claude Code')
    parser.add_argument('agent_id', help='Agent ID (e.g., 300)')
    parser.add_argument('--headless', action='store_true', help='Run without stdin (daemon mode)')
    parser.add_argument('--prompt-file', help='Path to custom system prompt file')
    parser.add_argument('--redis-host', default=None, help='Redis host')
    parser.add_argument('--redis-port', type=int, default=None, help='Redis port')
    args = parser.parse_args()

    if args.redis_host:
        global REDIS_HOST
        REDIS_HOST = args.redis_host
    if args.redis_port:
        global REDIS_PORT
        REDIS_PORT = args.redis_port

    agent = Agent(args.agent_id, headless=args.headless, prompt_file=args.prompt_file)

    if args.headless:
        agent.run_headless()
    else:
        agent.run_interactive()


if __name__ == "__main__":
    main()
