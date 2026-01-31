#!/usr/bin/env python3
"""
Agent Runner v3 - Session Resume Mode

Uses --session-id for first task, --resume for subsequent tasks.
Claude Code maintains conversation history, potential prompt caching.

Token savings: Depends on Anthropic's prompt caching
"""

import os
import sys
import json
import subprocess
import signal
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import logging

try:
    import redis
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "redis", "-q"])
    import redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)


class AgentRunnerV3:
    """Agent runner with session resume mode"""

    def __init__(self, role: str, agent_id: str, project: str, redis_url: str, profile: str = "default"):
        self.role = role
        self.agent_id = agent_id
        self.project = project
        self.redis_url = redis_url
        self.profile = profile

        self.redis: Optional[redis.Redis] = None
        self._running = False
        self.tasks_completed = 0
        self.tasks_in_session = 0
        self.sessions_created = 0

        # Session management
        self.session_id: Optional[str] = None
        self.session_initialized = False

        self.log = logging.getLogger(agent_id)

        # Setup directories - use script location as base
        base_dir = Path(__file__).parent.parent.parent
        self.log_dir = base_dir / "logs" / agent_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "claude.log"

    def connect_redis(self):
        """Connect to Redis"""
        host, port = "127.0.0.1", 6379
        if "://" in self.redis_url:
            hp = self.redis_url.split("://")[1]
            if ":" in hp:
                host, port = hp.split(":")
                port = int(port)

        self.redis = redis.Redis(host=host, port=port, decode_responses=True)
        self.redis.ping()
        self.log.info("Connected to Redis")

    def update_status(self, status: str, task: str = None):
        """Update agent status in Redis"""
        state = {
            "agent_id": self.agent_id,
            "role": self.role,
            "project": self.project,
            "profile": self.profile,
            "status": status,
            "current_task": task,
            "tasks_completed": self.tasks_completed,
            "sessions_created": self.sessions_created,
            "tasks_in_session": self.tasks_in_session,
            "session_id": self.session_id[:8] if self.session_id else None,
        }
        self.redis.hset("ma:agents", self.agent_id, json.dumps(state))

    def get_task(self) -> Optional[str]:
        """Get next task from queue"""
        queue_key = f"ma:inject:{self.agent_id}"
        processing_key = f"ma:processing:{self.agent_id}"
        task = self.redis.lmove(queue_key, processing_key, "LEFT", "RIGHT")
        return task

    def complete_task(self):
        """Mark current task as complete"""
        processing_key = f"ma:processing:{self.agent_id}"
        self.redis.delete(processing_key)

    def recover_tasks(self):
        """Recover incomplete tasks from previous run"""
        processing_key = f"ma:processing:{self.agent_id}"
        queue_key = f"ma:inject:{self.agent_id}"

        incomplete = self.redis.lrange(processing_key, 0, -1)
        if incomplete:
            self.log.info(f"Recovering {len(incomplete)} incomplete task(s)")
            for task in reversed(incomplete):
                self.redis.lpush(queue_key, task)
            self.redis.delete(processing_key)

    def load_system_prompt(self) -> str:
        """Load the agent's system prompt"""
        prompts_dir = Path(__file__).parent.parent.parent.parent / "prompts-v2"

        prompt_map = {
            "000": "000-mini-super.md",
            "100": "100-master.md",
            "200": "200-explorer.md",
            "201": "201-doc-generator.md",
            "203": "203-reconciler.md",
            "300": "300-dev-excel.md",
            "301": "301-dev-word.md",
            "302": "302-dev-pptx.md",
            "303": "303-dev-pdf.md",
            "400": "400-merge.md",
            "500": "500-test.md",
            "501": "501-test-creator.md",
            "502": "502-test-mapper.md",
            "600": "600-release.md",
        }

        filename = prompt_map.get(self.agent_id)
        if filename:
            prompt_file = prompts_dir / filename
            if prompt_file.exists():
                return prompt_file.read_text()

        return f"You are Agent {self.agent_id} ({self.role})."

    def new_session(self):
        """Create a new session"""
        self.session_id = str(uuid.uuid4())
        self.session_initialized = False
        self.tasks_in_session = 0
        self.sessions_created += 1
        self.log.info(f"New session #{self.sessions_created}: {self.session_id[:8]}")

    def run_claude(self, prompt: str, is_first: bool = False) -> str:
        """Run Claude with session management"""

        # Build command
        cmd = ["claude", "--dangerously-skip-permissions", "--print"]

        if is_first:
            # First task: create session with --session-id
            cmd.extend(["--session-id", self.session_id])
        else:
            # Subsequent tasks: resume session
            cmd.extend(["--resume", self.session_id])

        cmd.append("-")  # Read from stdin

        # Log prompt
        with open(self.log_file, "a") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] PROMPT (session={self.tasks_in_session}, first={is_first}, sid={self.session_id[:8]}):\n")
            preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
            f.write(preview + "\n")

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout.strip()

            if result.returncode != 0:
                error = result.stderr.strip()
                self.log.error(f"Claude error: {error}")
                output = f"Error: {error}"

            # Log response
            with open(self.log_file, "a") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] RESPONSE:\n")
                f.write(output + "\n")

            self.tasks_in_session += 1
            return output

        except subprocess.TimeoutExpired:
            self.log.error("Claude timeout")
            return "Error: Timeout"
        except Exception as e:
            self.log.error(f"Claude exception: {e}")
            return f"Error: {e}"

    def run(self):
        """Main agent loop"""
        self.connect_redis()
        self.recover_tasks()
        self._running = True
        self.new_session()

        self.log.info(f"Agent {self.agent_id} running in session resume mode (v3) [profile: {self.profile}]")

        def shutdown(sig, frame):
            self._running = False
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        # Load system prompt once
        system_prompt = self.load_system_prompt()

        while self._running:
            try:
                self.update_status("idle")

                # Get next task
                task = self.get_task()

                if task:
                    task_preview = task[:50] + "..." if len(task) > 50 else task
                    self.log.info(f"Task #{self.tasks_completed + 1} (session task #{self.tasks_in_session + 1}): {task_preview}")
                    self.update_status("busy", task_preview)

                    # Build prompt based on session state
                    if not self.session_initialized:
                        # First task in session: full prompt with system context
                        prompt = f"""{system_prompt}

---

## TÂCHE
{task}

EXÉCUTE MAINTENANT.
"""
                        response = self.run_claude(prompt, is_first=True)
                        self.session_initialized = True
                    else:
                        # Subsequent tasks: minimal prompt with --resume
                        prompt = f"""
---
NOUVELLE TÂCHE:
{task}

EXÉCUTE MAINTENANT.
"""
                        response = self.run_claude(prompt, is_first=False)

                    self.log.info(f"Response: {len(response)} chars")

                    # Mark complete
                    self.complete_task()
                    self.tasks_completed += 1
                    self.update_status("idle", None)

                else:
                    # No task, wait
                    time.sleep(2)

            except Exception as e:
                self.log.error(f"Error: {e}")
                self.update_status("error")
                time.sleep(5)

        self.update_status("stopped")
        self.log.info(f"Agent stopped. Total: {self.tasks_completed} tasks, {self.sessions_created} sessions")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["super-master", "master", "slave"], required=True)
    parser.add_argument("--id", dest="agent_id")
    parser.add_argument("--project", default="default")
    parser.add_argument("--redis", default="redis://127.0.0.1:6379")
    parser.add_argument("--profile", default="default")
    args = parser.parse_args()

    AgentRunnerV3(
        role=args.role,
        agent_id=args.agent_id or args.role,
        project=args.project,
        redis_url=args.redis,
        profile=args.profile
    ).run()


if __name__ == "__main__":
    main()
