#!/usr/bin/env python3
"""
healthcheck.py - Vérifie l'état de tous les agents
EF-002 : Watchdog auto-restart (CT-003: étend le code existant, nouvelles fonctions après)
CT-002 : Préfixe mi: pour streams monitoring
CT-009 : XTRIM MAXLEN ~1000 sur streams

Usage: python healthcheck.py [--watch] [--watchdog]

Options:
  --watch      Mode continu (refresh toutes les 2s)
  --watchdog   Mode watchdog avec auto-restart (EF-002)
"""

import redis
import time
import sys
import os
import argparse
import subprocess
import json
import logging
from urllib.request import urlopen
from urllib.error import URLError

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
MA_PREFIX = os.environ.get("MA_PREFIX", "A")
MONITORING_PREFIX = os.environ.get("MONITORING_PREFIX", MA_PREFIX)
HEALTH_PORT_BASE = int(os.environ.get("AGENT_HEALTH_PORT_BASE", 9100))

# EF-002: Watchdog configuration
WATCHDOG_POLL_INTERVAL = int(os.environ.get("WATCHDOG_POLL_INTERVAL", 5))
WATCHDOG_FAIL_THRESHOLD = int(os.environ.get("WATCHDOG_FAIL_THRESHOLD", 3))
WATCHDOG_HEALTH_TIMEOUT = int(os.environ.get("WATCHDOG_HEALTH_TIMEOUT", 2))
CIRCUIT_BREAKER_MAX_RESTARTS = int(os.environ.get("CIRCUIT_BREAKER_MAX_RESTARTS", 3))
CIRCUIT_BREAKER_WINDOW = int(os.environ.get("CIRCUIT_BREAKER_WINDOW", 300))
STREAM_MAXLEN = 1000  # CT-009

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)

logger = logging.getLogger("healthcheck")


# ============================================================
# EXISTING CODE — check_agents, print_status, check_streams
# CT-003: Ce code est INCHANGÉ par rapport à l'original (147L)
# ============================================================

def check_agents():
    """Liste et vérifie tous les agents"""
    agents = {}

    for key in r.keys(f"{MA_PREFIX}:agent:*"):
        # Filtrer pour avoir seulement A:agent:XXX (pas inbox/outbox)
        parts = key.split(':')
        if len(parts) == 3:  # A:agent:XXX
            agent_id = parts[2]
            data = r.hgetall(key)

            if not data:
                continue

            last_seen = int(data.get('last_seen', 0))
            age = time.time() - last_seen

            agents[agent_id] = {
                'status': data.get('status', 'unknown'),
                'queue': data.get('queue_size', '?'),
                'task_from': data.get('current_task_from', ''),
                'headless': data.get('headless', 'false'),
                'session': data.get('session_id', '')[:8],
                'tasks': data.get('tasks_completed', '0'),
                'age_seconds': int(age),
                'healthy': age < 30  # Moins de 30s depuis dernier heartbeat
            }

    return agents


def print_status(agents, clear=False):
    """Affiche le status des agents"""
    if clear:
        print("\033[2J\033[H", end='')  # Clear screen

    print("Multi-Agent Health Check")
    print("=" * 80)
    print(f"{'ID':<6} {'Status':<10} {'Queue':<6} {'Tasks':<6} {'Session':<10} {'Age':<10} {'Health'}")
    print("-" * 80)

    for agent_id, info in sorted(agents.items(), key=lambda x: x[0]):
        status = info['status']
        # Couleurs
        if status == 'idle':
            status_str = f"\033[32m{status:<10}\033[0m"  # vert
        elif status == 'busy':
            status_str = f"\033[33m{status:<10}\033[0m"  # jaune
        else:
            status_str = f"\033[31m{status:<10}\033[0m"  # rouge

        health = "\033[32mOK\033[0m" if info['healthy'] else "\033[31mSTALE\033[0m"
        age = f"{info['age_seconds']}s"

        print(f"{agent_id:<6} {status_str} {info['queue']:<6} {info['tasks']:<6} {info['session']:<10} {age:<10} {health}")

    print("-" * 80)

    healthy_count = sum(1 for i in agents.values() if i['healthy'])
    total = len(agents)
    print(f"Total: {total} agents, {healthy_count} healthy, {total - healthy_count} stale")

    unhealthy = [a for a, i in agents.items() if not i['healthy']]
    if unhealthy:
        print(f"\n\033[33mWarning:\033[0m Stale agents: {', '.join(sorted(unhealthy))}")

    return len(unhealthy) == 0


def check_streams():
    """Vérifie les streams Redis"""
    print("\n" + "=" * 80)
    print("Redis Streams Status")
    print("-" * 80)

    for key in sorted(r.keys(f"{MA_PREFIX}:agent:*:inbox") + r.keys(f"{MA_PREFIX}:agent:*:outbox")):
        try:
            info = r.xinfo_stream(key)
            length = info.get('length', 0)
            last_id = info.get('last-generated-id', '-')
            print(f"  {key}: {length} messages, last={last_id}")
        except redis.ResponseError:
            pass  # Stream doesn't exist yet


# ============================================================
# EF-002 — Watchdog auto-restart (NOUVEAU CODE, ajouté après)
# CT-003: Nouvelles fonctions, code existant INCHANGÉ ci-dessus
# ============================================================

class AgentWatchdog:
    """Watchdog avec auto-restart et circuit breaker (EF-002, CA-002, CA-003).

    Découvre les agents via Redis heartbeat streams (mi:agent:*:heartbeat).
    Interroge /health de chaque agent toutes les 5s (CA-002).
    3 checks échoués → redémarrage (CA-002: détection+restart < 25s).
    Circuit breaker: 3 restarts par 5 min par agent (CA-003).
    """

    def __init__(self, redis_client, prefix=None, health_port_base=None,
                 poll_interval=None, fail_threshold=None, health_timeout=None,
                 max_restarts=None, breaker_window=None):
        """EF-002 : Initialise le watchdog avec seuils configurables."""
        self.redis = redis_client
        self.prefix = prefix or MONITORING_PREFIX
        self.health_port_base = health_port_base or HEALTH_PORT_BASE
        self.poll_interval = poll_interval or WATCHDOG_POLL_INTERVAL
        self.fail_threshold = fail_threshold or WATCHDOG_FAIL_THRESHOLD
        self.health_timeout = health_timeout or WATCHDOG_HEALTH_TIMEOUT
        self.max_restarts = max_restarts or CIRCUIT_BREAKER_MAX_RESTARTS
        self.breaker_window = breaker_window or CIRCUIT_BREAKER_WINDOW
        self._fail_counts = {}       # agent_id → consecutive failures
        self._restart_history = {}   # agent_id → [timestamps]
        self._circuit_open = {}      # agent_id → bool

    def discover_agents(self):
        """Découvre les agents actifs via Redis heartbeat streams (EF-002).

        Primary: KEYS mi:agent:*:heartbeat (source de vérité: tout agent vivant publie).
        Fallback: tmux list-sessions si Redis injoignable.
        """
        agents = set()
        try:
            for key in self.redis.keys(f"{self.prefix}:agent:*:heartbeat"):
                parts = key.split(':')
                if len(parts) == 4:
                    agents.add(parts[2])
        except Exception:
            agents = self._discover_tmux_fallback()
        return sorted(agents)

    def _discover_tmux_fallback(self):
        """Fallback tmux pour découverte agents (EF-002)."""
        agents = set()
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.startswith("agent-") or line.startswith("A-agent-"):
                        agent_id = line.replace("A-agent-", "").replace("agent-", "")
                        agents.add(agent_id)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return agents

    def check_health(self, agent_id):
        """Interroge /health d'un agent — EF-002, CA-002 (timeout 2s)."""
        try:
            numeric_id = int(agent_id.split('-')[0])
        except (ValueError, IndexError):
            return None
        port = self.health_port_base + numeric_id
        url = f"http://localhost:{port}/health"
        try:
            resp = urlopen(url, timeout=self.health_timeout)
            data = json.loads(resp.read().decode())
            return data
        except (URLError, OSError, json.JSONDecodeError, ValueError):
            return None

    def restart_agent(self, agent_id):
        """Redémarre un agent via tmux — EF-002, CA-002."""
        session_name = f"A-agent-{agent_id}"
        try:
            result = subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "C-c", ""],
                capture_output=True, text=True, timeout=5)
            time.sleep(1)
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name,
                 f"python3 agent.py {agent_id}", "Enter"],
                capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _record_restart(self, agent_id):
        """Enregistre un restart et vérifie le circuit breaker (CA-003)."""
        now = time.time()
        if agent_id not in self._restart_history:
            self._restart_history[agent_id] = []
        self._restart_history[agent_id].append(now)
        # Nettoyer les vieux restarts hors fenêtre
        cutoff = now - self.breaker_window
        self._restart_history[agent_id] = [
            ts for ts in self._restart_history[agent_id] if ts > cutoff]

    def is_circuit_open(self, agent_id):
        """Vérifie si le circuit breaker est ouvert (CA-003)."""
        if self._circuit_open.get(agent_id):
            return True
        history = self._restart_history.get(agent_id, [])
        cutoff = time.time() - self.breaker_window
        recent = [ts for ts in history if ts > cutoff]
        if len(recent) >= self.max_restarts:
            self._circuit_open[agent_id] = True
            return True
        return False

    def _publish_event(self, event_type, agent_id, details=None):
        """Publie un événement monitoring — CT-002, CT-009 (R-XTRIM)."""
        event = {
            "from": "watchdog",
            "type": event_type,
            "agent_id": agent_id,
            "timestamp": str(int(time.time())),
            "payload": json.dumps(details or {})
        }
        stream = f"{self.prefix}:monitoring:restart"
        self.redis.xadd(stream, event, maxlen=STREAM_MAXLEN, approximate=True)
        return event

    def _publish_alert(self, level, agent_id, message, details=None):
        """Publie une alerte critique — EF-004 intégration, CT-009."""
        alert = {
            "from": "watchdog",
            "type": f"alert:{level}",
            "agent_id": agent_id,
            "message": message,
            "timestamp": str(int(time.time())),
            "payload": json.dumps(details or {})
        }
        stream = f"{self.prefix}:monitoring:alerts"
        self.redis.xadd(stream, alert, maxlen=STREAM_MAXLEN, approximate=True)
        return alert

    def process_agent(self, agent_id):
        """Traite un agent: check health → restart si nécessaire (EF-002).

        Returns:
            str: 'healthy', 'restarted', 'circuit_open', 'failed'
        """
        health = self.check_health(agent_id)

        if health and health.get("status") in ("healthy", "degraded"):
            # Agent OK — reset fail count
            if self._fail_counts.get(agent_id, 0) > 0:
                self._publish_event("agent_recovered", agent_id)
            self._fail_counts[agent_id] = 0
            if self._circuit_open.get(agent_id):
                self._circuit_open[agent_id] = False
            return "healthy"

        # Health check failed
        self._fail_counts[agent_id] = self._fail_counts.get(agent_id, 0) + 1

        if self._fail_counts[agent_id] < self.fail_threshold:
            return "failing"

        # Threshold reached — attempt restart
        if self.is_circuit_open(agent_id):
            self._publish_alert("critical", agent_id,
                f"Circuit breaker open for agent {agent_id}: "
                f"{self.max_restarts} restarts in {self.breaker_window}s",
                {"restarts": len(self._restart_history.get(agent_id, []))})
            return "circuit_open"

        # Restart
        self._publish_event("agent_restart", agent_id,
            {"reason": f"{self.fail_threshold} consecutive health check failures",
             "fail_count": self._fail_counts[agent_id]})
        success = self.restart_agent(agent_id)
        self._record_restart(agent_id)
        self._fail_counts[agent_id] = 0

        if success:
            self._publish_event("agent_restarted", agent_id)
            return "restarted"
        else:
            self._publish_alert("warning", agent_id,
                f"Failed to restart agent {agent_id}")
            return "failed"

    def run_cycle(self):
        """Exécute un cycle watchdog complet (EF-002)."""
        agents = self.discover_agents()
        results = {}
        for agent_id in agents:
            results[agent_id] = self.process_agent(agent_id)
        return results

    def run(self):
        """Boucle principale watchdog (EF-002, CA-002: poll every 5s)."""
        logger.info("Watchdog started (poll=%ds, fail=%d, breaker=%d/%ds)",
                     self.poll_interval, self.fail_threshold,
                     self.max_restarts, self.breaker_window)
        try:
            while True:
                results = self.run_cycle()
                for agent_id, status in results.items():
                    if status != "healthy":
                        logger.info("Agent %s: %s", agent_id, status)
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Watchdog stopped.")


def main():
    parser = argparse.ArgumentParser(description='Multi-Agent Health Check')
    parser.add_argument('--watch', action='store_true', help='Continuous monitoring mode')
    parser.add_argument('--watchdog', action='store_true', help='Watchdog mode with auto-restart (EF-002)')
    parser.add_argument('--streams', action='store_true', help='Show stream stats')
    parser.add_argument('--interval', type=int, default=2, help='Refresh interval in watch mode')
    args = parser.parse_args()

    try:
        r.ping()
    except redis.ConnectionError:
        print(f"\033[31mError:\033[0m Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
        return 1

    if args.watchdog:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s [watchdog] %(message)s')
        watchdog = AgentWatchdog(r)
        watchdog.run()
        return 0

    if args.watch:
        print("Watching agents (Ctrl+C to quit)...")
        try:
            while True:
                agents = check_agents()
                print_status(agents, clear=True)
                if args.streams:
                    check_streams()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
    else:
        agents = check_agents()
        if not agents:
            print("No agents found in Redis")
            return 0

        all_healthy = print_status(agents)
        if args.streams:
            check_streams()

        return 0 if all_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
