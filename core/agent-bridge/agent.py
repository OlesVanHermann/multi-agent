#!/usr/bin/env python3
"""
agent-tmux.py - Agent bridge using tmux to communicate with interactive Claude

Instead of subprocess with --print, this uses:
- tmux send-keys: send prompts to Claude
- tmux capture-pane: read Claude's output
- Claude runs in FULL INTERACTIVE MODE with MCP access!

Usage: python agent-tmux.py <AGENT_ID>

Requires: tmux session "agent-{id}" with Claude running interactively
"""

import sys
import os
import time
import subprocess
import re
import argparse
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
MA_PREFIX = os.environ.get("MA_PREFIX", "ma")

MAX_HISTORY = 50
RESPONSE_TIMEOUT = 300  # 5 min max wait for Claude response
POLL_INTERVAL = 1.0     # How often to check for new output (was 0.3 — too CPU intensive)

# Claude prompt markers (to detect end of response)
PROMPT_MARKERS = ['❯', '>', '$', '%']


class State(Enum):
    IDLE = "idle"
    BUSY = "busy"


class TmuxAgent:
    def __init__(self, agent_id):
        self.agent_id = str(agent_id)
        self.session_name = f"{MA_PREFIX}-agent-{agent_id}"
        self.state = State.IDLE
        self.state_lock = Lock()

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
        ]
        for t in self.threads:
            t.start()

        self._set_redis_status()
        self._log(f"Listening: Redis={self.inbox} + {self.legacy_inbox}, tmux={self.session_name}")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}][{self.agent_id}] {msg}"
        print(line, flush=True)
        self.logfile.write(line + "\n")

    def _tmux_session_exists(self):
        """Check if tmux session exists"""
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            capture_output=True
        )
        return result.returncode == 0

    def _get_pane_line_count(self):
        """Get current number of lines in tmux pane 0"""
        target = f"{self.session_name}.0"
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True, text=True
        )
        return len(result.stdout.split('\n'))

    def _capture_pane(self, lines=100):
        """Capture tmux pane 0 content (where Claude runs)"""
        target = f"{self.session_name}.0"
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True
        )
        return result.stdout

    def _send_keys(self, text):
        """Send keys to tmux pane 0 (where Claude runs)"""
        # Target pane 0 specifically (Claude is in pane 0, bridge is in pane 1)
        target = f"{self.session_name}.0"

        # Clear any existing input first
        subprocess.run(["tmux", "send-keys", "-t", target, "C-c"], capture_output=True)
        time.sleep(0.5)
        subprocess.run(["tmux", "send-keys", "-t", target, "C-u"], capture_output=True)
        time.sleep(0.5)

        # Send text
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "-l", text],
            capture_output=True
        )

        # Wait 1 second for text to be received
        time.sleep(1)

        # Send Escape (exits multi-line mode if active)
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Escape"],
            capture_output=True
        )

        # Wait 1 second for Escape to be processed
        time.sleep(1)

        # Send Enter to submit
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

            # Check if content changed
            if current != last_content:
                last_content = current
                stable_count = 0
                if hash(current) != baseline_hash:
                    response_started = True

                # Print new content in real-time
                current_lines = current.strip().split('\n')
                if len(current_lines) > last_printed:
                    for line in current_lines[last_printed:][-5:]:
                        if line.strip():
                            print(f"  {line}", flush=True)
                    last_printed = len(current_lines)
            else:
                stable_count += 1

            # Check for prompt marker (Claude is done)
            current_lines = current.strip().split('\n')
            last_line = current_lines[-1].strip() if current_lines else ""
            for marker in PROMPT_MARKERS:
                if last_line.endswith(marker) or last_line == marker:
                    if response_started and stable_count >= 2:
                        # Return full captured content (not baseline-relative)
                        response = '\n'.join(current_lines[:-1]).strip()
                        return response

            # If stable for a while and we got content, consider it done
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

        # Capture baseline
        print(f"\n{'─'*60}", flush=True)
        print(f"📤 CLAUDE (tmux interactive):", flush=True)
        print(f"{'─'*60}", flush=True)

        # Send prompt
        self._send_keys(prompt)

        # Wait for response
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

                            # Forward response to Claude in tmux (compact format)
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
                time.sleep(1)

    def _listen_legacy(self):
        """Thread: listen to legacy Redis inbox (List format: ma:inject:{id})

        Supports FROM:xxx| prefix to identify sender:
          RPUSH ma:inject:300 "FROM:100|do something"
        """
        while self.running:
            try:
                # BLPOP blocks until message available (timeout 2s)
                result = self.redis.blpop(self.legacy_inbox, timeout=2)
                if result:
                    _, message = result

                    # Parse FROM:xxx| prefix if present
                    from_agent = 'legacy'
                    prompt = message
                    if message.startswith('FROM:'):
                        parts = message.split('|', 1)
                        if len(parts) == 2:
                            from_agent = parts[0][5:]  # Remove "FROM:" prefix
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

            # Run prompt
            response = self._run_claude(task['prompt'])

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

            # Notify sender if it was another agent
            from_agent = task.get('from_agent')

            if from_agent and from_agent not in ['manual', 'cli', 'auto_init', 'unknown', 'legacy', 'compaction_reload']:
                try:
                    # Send FULL response - no truncation
                    # For very long responses, split into chunks
                    MAX_CHUNK = 15000  # Redis can handle larger messages

                    if len(response) <= MAX_CHUNK:
                        self.redis.xadd(f"{MA_PREFIX}:agent:{from_agent}:inbox", {
                            'response': response,
                            'from_agent': self.agent_id,
                            'type': 'response',
                            'timestamp': int(time.time()),
                            'complete': 'true'
                        })
                    else:
                        # Split into chunks for very long responses
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
        prompt_file = self._find_prompt_file()
        if prompt_file:
            self._log(f"Auto-loading: {prompt_file}")
            self.prompt_queue.put({
                'prompt': f"deviens agent {prompt_file}",
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
            self.logfile.close()

    def _reload_prompt(self):
        """Reload agent prompt file to restore personality after context compaction"""
        prompt_file = self._find_prompt_file()
        if prompt_file:
            self._log(f"RELOAD: {prompt_file} (with /reset to clear thinking blocks)")
            self.messages_since_reload = 0

            # First, reset the conversation to clear thinking blocks
            # This prevents API error: "thinking blocks cannot be modified"
            self._send_keys("/reset")
            time.sleep(2)  # Wait for reset to complete

            # Then inject the prompt
            self.prompt_queue.put({
                'prompt': f"deviens agent {prompt_file}",
                'from_agent': 'compaction_reload',
                'msg_id': f"reload_{int(time.time())}",
            })
            self._set_redis_status()

    def _find_prompt_file(self):
        """Find prompt file for this agent"""
        prompts_dir = BASE_DIR / "prompts"
        pattern = f"{self.agent_id}-*.md"
        matches = list(prompts_dir.glob(pattern))
        if matches:
            return str(matches[0])
        return None

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
