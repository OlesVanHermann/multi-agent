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
import re
import time
import sys
import os
import argparse
import subprocess
import json
import logging
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# A6 : source unique du format d'ID agent
from ids import is_valid_agent_id

# V3/C2 : détection de stall via le WAL
import wal
import obligations

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
HEALTH_PORT_BASE = int(os.environ.get("AGENT_HEALTH_PORT_BASE", 9100))
HEALTH_TOKEN = os.environ.get("HEALTH_TOKEN", "")

# EF-002: Watchdog configuration
WATCHDOG_POLL_INTERVAL = int(os.environ.get("WATCHDOG_POLL_INTERVAL", 5))
WATCHDOG_FAIL_THRESHOLD = int(os.environ.get("WATCHDOG_FAIL_THRESHOLD", 3))
WATCHDOG_HEALTH_TIMEOUT = int(os.environ.get("WATCHDOG_HEALTH_TIMEOUT", 2))
CIRCUIT_BREAKER_MAX_RESTARTS = int(os.environ.get("CIRCUIT_BREAKER_MAX_RESTARTS", 3))
CIRCUIT_BREAKER_WINDOW = int(os.environ.get("CIRCUIT_BREAKER_WINDOW", 300))
# V3/C2 : agent busy sans événement WAL au-delà de ce seuil → nudge puis escalade
WATCHDOG_STALL_THRESHOLD = int(os.environ.get("WATCHDOG_STALL_THRESHOLD", 600))
OBLIGATION_REMINDER_S = int(os.environ.get("OBLIGATION_REMINDER_S", 900))
# A8 : un message stocké mais jamais lu au-delà de cette échéance est une
# violation de l'invariant « un message envoyé finit par être lu ».
UNREAD_DEADLINE_S = int(os.environ.get("UNREAD_DEADLINE_S", 900))
# A8 : bridge dont le code chargé est plus vieux que le disque au-delà de
# cette marge → STALE_BRIDGE (les correctifs Python attendent un reload).
STALE_BRIDGE_GRACE_S = int(os.environ.get("STALE_BRIDGE_GRACE_S", 900))
STREAM_MAXLEN = 1000  # CT-009
IO_STREAM_MAXLEN = int(os.environ.get("IO_STREAM_MAXLEN", 10000))
BASE_DIR = Path(__file__).resolve().parents[2]

# A8 : streams parqués dont l'annexation est promise par le bridge — le
# watchdog vérifie que la promesse est tenue dans le délai.
PARKED_STREAM_SUFFIXES = ("reports", "control", "terminals", "supervision")


def bridge_code_mtime_on_disk(root=None):
    """Empreinte du code bridge sur disque (miroir de agent._bridge_code_mtime).

    Dupliquée volontairement : importer agent.py ici chargerait la couche
    moteur (markers fail-fast) dans un process qui n'en a pas besoin.
    """
    newest = 0.0
    base = Path(root) if root else Path(__file__).parent
    for pattern in ("*.py", "*.lua", "*.yaml"):
        for path in base.glob(pattern):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    return int(newest)

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)

logger = logging.getLogger("healthcheck")


# ============================================================
# EXISTING CODE — check_agents, print_status, check_streams
# CT-003: Ce code est INCHANGÉ par rapport à l'original (147L)
# ============================================================

def check_agents():
    """Liste et vérifie tous les agents"""
    agents = {}

    for key in r.keys(f"agent:*"):
        # Filtrer pour avoir seulement agent:XXX (pas inbox/outbox)
        parts = key.split(':')
        if len(parts) == 2:
            agent_id = parts[1]
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

    for key in sorted(r.keys(f"agent:*:inbox") + r.keys(f"agent:*:outbox")):
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

    Découvre les agents via Redis heartbeat streams (agent:*:heartbeat).
    Interroge /health de chaque agent toutes les 5s (CA-002).
    3 checks échoués → redémarrage (CA-002: détection+restart < 25s).
    Circuit breaker: 3 restarts par 5 min par agent (CA-003).
    """

    def __init__(self, redis_client, health_port_base=None,
                 poll_interval=None, fail_threshold=None, health_timeout=None,
                 max_restarts=None, breaker_window=None, stall_threshold=None,
                 obligation_reminder_s=None, base_dir=None):
        """EF-002 : Initialise le watchdog avec seuils configurables."""
        self.redis = redis_client
        self.health_port_base = health_port_base or HEALTH_PORT_BASE
        self.poll_interval = poll_interval or WATCHDOG_POLL_INTERVAL
        self.fail_threshold = fail_threshold or WATCHDOG_FAIL_THRESHOLD
        self.health_timeout = health_timeout or WATCHDOG_HEALTH_TIMEOUT
        self.max_restarts = max_restarts or CIRCUIT_BREAKER_MAX_RESTARTS
        self.breaker_window = breaker_window or CIRCUIT_BREAKER_WINDOW
        self.stall_threshold = stall_threshold or WATCHDOG_STALL_THRESHOLD
        self.obligation_reminder_s = (
            obligation_reminder_s or OBLIGATION_REMINDER_S)
        self.base_dir = Path(base_dir or BASE_DIR)
        self._fail_counts = {}       # agent_id → consecutive failures
        self._restart_history = {}   # agent_id → [timestamps]
        self._circuit_open = {}      # agent_id → bool
        self._nudged = {}            # V3/C2 : agent_id → 'nudged'|'escalated'
        # Dédup en mémoire des alertes d'état durable (auth_blocked,
        # consumer_down) : une alerte par transition d'état, pas une par
        # cycle de 5 s. En mémoire car sous Redis MISCONF les SET échouent.
        self._alert_states = {}      # agent_id → dernier état alerté
        # A8 : suivi de l'invariant de lecture et de la fraîcheur du code.
        self._unread_alerted = {}    # agent_id → bool (alerte backlog émise)
        self._inbox_lag_first_seen = {}  # agent_id → ts première observation
        self._stale_alerted = {}     # agent_id → bool (alerte STALE_BRIDGE)

    def _send_status_required(self, agent_id, data, message):
        """Persiste un contrôle sans réveiller le modèle."""
        self.redis.xadd(
            f"agent:{agent_id}:control", {
                "from_agent": "watchdog",
                "event": "STATUS_REQUIRED",
                "classification": "control",
                "detail": message,
                "task_id": data.get("task_id", ""),
                "cycle": data.get("cycle", ""),
                "correlation_id": data.get("correlation_id", ""),
                "requester": data.get("requester", ""),
                "owner": data.get("owner", "") or agent_id,
                "timestamp": int(time.time()),
            }, maxlen=IO_STREAM_MAXLEN, approximate=True)
        return type(
            "ControlStored", (), {
                "returncode": 0, "stdout": "state=STORED", "stderr": ""})()

    def _check_obligations(self, now=None):
        """Réconcilie, rappelle puis escalade les obligations ouvertes."""
        now = time.time() if now is None else now
        results = {}
        try:
            obligations.reconcile(self.redis, self.base_dir)
            open_items = list(obligations.iter_open(self.base_dir) or [])
        except Exception as exc:
            logger.warning("obligation reconciliation error: %s", exc)
            return results
        for path, data in open_items:
            agent_id = data.get("owner", "")
            if not is_valid_agent_id(agent_id):
                continue
            age = now - int(data.get("received_at", now))
            if data.get("escalated_at"):
                results[agent_id] = "obligation_escalated"
                continue
            if age >= 2 * self.obligation_reminder_s and data.get("reminder_at"):
                self._publish_alert(
                    "critical", agent_id,
                    f"Terminal attendu absent depuis {int(age)}s",
                    {
                        "task_id": data.get("task_id", ""),
                        "cycle": data.get("cycle", ""),
                        "correlation_id": data.get("correlation_id", ""),
                        "expected_event": data.get("expected_event", ""),
                    })
                wal.emit(
                    self.redis, None, "obligation_escalation", agent_id,
                    data.get("task_id"),
                    cycle=data.get("cycle", ""),
                    correlation_id=data.get("correlation_id", ""),
                    expected_event=data.get("expected_event", ""),
                    age_seconds=int(age))
                obligations.update(path, escalated_at=int(now))
                results[agent_id] = "obligation_escalated"
                continue
            if age >= self.obligation_reminder_s and not data.get("reminder_at"):
                message = (
                    "Terminal manquant : "
                    f"TASK={data.get('task_id', '')} "
                    f"CYCLE={data.get('cycle', '')} "
                    f"CORR={data.get('correlation_id', '')} "
                    f"EXPECTED_EVENT={data.get('expected_event', '')}. "
                    "Vérifie ton état durable et émets le terminal dû ; "
                    "ne recommence pas le travail.")
                result = self._send_status_required(agent_id, data, message)
                if result.returncode in (0, 2):
                    obligations.update(path, reminder_at=int(now))
                    wal.emit(
                        self.redis, None, "obligation_reminder", agent_id,
                        data.get("task_id"),
                        cycle=data.get("cycle", ""),
                        correlation_id=data.get("correlation_id", ""),
                        expected_event=data.get("expected_event", ""),
                        age_seconds=int(age))
                    results[agent_id] = "obligation_reminded"
                else:
                    logger.warning(
                        "obligation reminder failed for %s: %s",
                        agent_id, result.stderr.strip())
        return results

    def discover_agents(self):
        """Découvre les agents actifs via Redis heartbeat streams (EF-002).

        Primary: KEYS agent:*:heartbeat (source de vérité: tout agent vivant publie).
        Fallback: tmux list-sessions si Redis injoignable.
        """
        agents = set()
        try:
            for key in self.redis.scan_iter(match="agent:*:heartbeat"):
                parts = key.split(':')
                if len(parts) == 3:
                    candidate = parts[1]
                    if is_valid_agent_id(candidate):
                        agents.add(candidate)
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
                    if line.startswith("agent-"):
                        agent_id = line.replace("agent-", "", 1)
                        agents.add(agent_id)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return agents

    def check_health(self, agent_id):
        """Interroge /health d'un agent — EF-002, CA-002 (timeout 2s)."""
        if not is_valid_agent_id(agent_id):
            return None
        published_port = self.redis.hget(
            f"agent:{agent_id}", "health_port")
        if isinstance(published_port, bytes):
            published_port = published_port.decode(errors="replace")
        try:
            port = int(published_port)
        except (TypeError, ValueError):
            port = 0
        if not (1 <= port <= 65535):
            return None
        url = f"http://localhost:{port}/health"
        try:
            headers = (
                {"Authorization": f"Bearer {HEALTH_TOKEN}"}
                if HEALTH_TOKEN else {}
            )
            request = Request(url, headers=headers)
            resp = urlopen(request, timeout=self.health_timeout)
            data = json.loads(resp.read().decode())
            return data
        except (URLError, OSError, json.JSONDecodeError, ValueError):
            return None

    def restart_agent(self, agent_id):
        """Redémarre un agent avec le gestionnaire canonique — EF-002, CA-002.

        Le watchdog ne doit jamais injecter de touches dans le pane moteur.
        Si le CLI est encore actif, ``C-c`` le tue ; s'il est déjà sorti, le
        texte de relance est exécuté par le shell du pane. ``agent.sh`` est la
        source de vérité pour reconstruire ensemble session, moteur, profil et
        bridge.
        """
        if not is_valid_agent_id(agent_id):
            logger.warning("restart_agent: invalid agent_id format: %s", agent_id)
            return False
        agent_script = Path(__file__).resolve().parents[1] / "agent.sh"
        try:
            result = subprocess.run(
                [str(agent_script), "restart", agent_id],
                capture_output=True, text=True, timeout=30,
                cwd=str(agent_script.parent.parent))
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
        stream = "monitoring:restart"
        try:
            self.redis.xadd(
                stream, event, maxlen=STREAM_MAXLEN, approximate=True)
        except Exception as exc:
            logger.warning("event publish failed for %s: %s", agent_id, exc)
        return event

    def _publish_alert(self, level, agent_id, message, details=None):
        """Publie une alerte critique — EF-004 intégration, CT-009.

        Best-effort : sous Redis MISCONF (écritures refusées), l'incident
        que l'alerte décrit ferait crasher le watchdog lui-même. Une panne
        de publication ne tue jamais la boucle de surveillance.
        """
        alert = {
            "from": "watchdog",
            "type": f"alert:{level}",
            "agent_id": agent_id,
            "message": message,
            "timestamp": str(int(time.time())),
            "payload": json.dumps(details or {})
        }
        stream = "monitoring:alerts"
        try:
            self.redis.xadd(
                stream, alert, maxlen=STREAM_MAXLEN, approximate=True)
        except Exception as exc:
            logger.warning("alert publish failed for %s: %s", agent_id, exc)
        return alert

    def _check_stall(self, agent_id):
        """V3/C2 : agent busy sans événement WAL depuis stall_threshold.

        1er dépassement → alerte warning + nudge dans l'inbox. Le nudge est
        lui-même un événement WAL : il remet le compteur à zéro, l'agent a
        donc une fenêtre COMPLÈTE pour montrer de l'activité.
        2e dépassement → alerte critique + WAL escalation (motif=stall),
        puis silence (état 'escalated' — pas de spam d'alertes).
        Toute activité WAL réelle (hors nudge/escalation) réarme la machine.

        Le WAL et le hash de statut utilisent les clés canoniques écrites par
        le bridge.
        """
        try:
            agent_state = self.redis.hgetall(f"agent:{agent_id}")
            status = agent_state.get("status")
            if status != "busy":
                self._nudged.pop(agent_id, None)
                return None
            correlation_id = agent_state.get("current_correlation", "")
            task_id = agent_state.get("current_task_id", "")
            cycle = agent_state.get("current_cycle", "")
            requester = agent_state.get("current_requester", "")
            last = wal.last_event(self.redis, None, agent_id)
            if not last:
                return None  # bridge sans WAL (v2) : pas de faux positif
            data = last[1]
            age = time.time() - int(data.get("ts", 0))
            if age < self.stall_threshold:
                if data.get("event") not in (
                        "nudge", "escalation", "terminal_pending"):
                    self._nudged.pop(agent_id, None)  # activité réelle
                return None
            # Le silence et le temps écoulé sont des observations, jamais une
            # preuve d'échec métier. Le watchdog rend l'écart visible une fois
            # sans réveiller le modèle, sans redispatch et sans fabriquer de
            # PROTOCOL_ERROR.
            if self._nudged.get(agent_id) != "observed":
                details = {
                    "age_seconds": int(age),
                    "motif": "terminal_pending",
                    "correlation_id": correlation_id,
                    "task_id": task_id,
                    "cycle": cycle,
                }
                self._publish_alert(
                    "warning", agent_id,
                    f"Agent {agent_id} busy sans activité WAL depuis "
                    f"{int(age)}s — observation seulement",
                    details)
                pending_event = {
                    "from_agent": "watchdog",
                    "event": "TERMINAL_PENDING",
                    "classification": "control",
                    "detail": (
                        "Silence observé; aucun timeout métier ni "
                        "redispatch automatique"),
                    "correlation_id": correlation_id,
                    "task_id": task_id,
                    "cycle": cycle,
                    "requester": requester,
                    "owner": agent_id,
                    "timestamp": int(time.time()),
                }
                self.redis.xadd(
                    f"agent:{agent_id}:control", pending_event,
                    maxlen=IO_STREAM_MAXLEN, approximate=True)
                # Le demandeur en WAITING doit pouvoir constater le silence
                # de sa cible : même constat sur SON stream control, drainé
                # sans réveil au prochain vrai tour (aucun rapport dû).
                if (requester and requester != agent_id
                        and is_valid_agent_id(requester)):
                    self.redis.xadd(
                        f"agent:{requester}:control", pending_event,
                        maxlen=IO_STREAM_MAXLEN, approximate=True)
                wal.emit(
                    self.redis, None, "terminal_pending", agent_id,
                    task_id=task_id, cycle=cycle,
                    correlation_id=correlation_id,
                    age_seconds=int(age))
                self._nudged[agent_id] = "observed"
            return "stalled"
        except Exception as exc:
            # la détection de stall ne doit jamais casser le watchdog restart
            logger.warning("stall check error for %s: %s", agent_id, exc)
            return None

    def process_agent(self, agent_id):
        """Traite un agent: check health → restart si nécessaire (EF-002).

        Returns:
            str: 'healthy', 'stalled', 'restarted', 'circuit_open', 'failed'
        """
        health = self.check_health(agent_id)

        if health and health.get("status") in ("healthy", "degraded"):
            if health.get("auth_blocked"):
                # Une alerte par transition d'état, pas une par cycle :
                # l'état est durable (opérateur requis).
                if self._alert_states.get(agent_id) != "auth_blocked":
                    self._alert_states[agent_id] = "auth_blocked"
                    self._publish_alert(
                        "critical", agent_id,
                        f"Agent {agent_id}: session moteur AUTH_BLOCKED",
                        {"auth_blocked": True})
                return "auth_blocked"
            listeners = health.get("listeners") or {}
            consumer_states = {
                listeners.get(name, {}).get("state")
                for name in ("redis_listener", "legacy_listener")
                if name in listeners
            }
            # 'starting' (démarrage) et 'stopped' (arrêt en cours) sont des
            # transitions normales, pas un consommateur dégradé.
            degraded_states = consumer_states - {"up", "starting", "stopped"}
            if degraded_states:
                if self._alert_states.get(agent_id) != "consumer_down":
                    self._alert_states[agent_id] = "consumer_down"
                    self._publish_alert(
                        "critical", agent_id,
                        f"Agent {agent_id}: processus vivant mais "
                        "consommateur dégradé",
                        {"listeners": listeners})
                return "consumer_down"
            # Agent OK — reset fail count et dédup d'alerte
            self._alert_states.pop(agent_id, None)
            if self._fail_counts.get(agent_id, 0) > 0:
                self._publish_event("agent_recovered", agent_id)
            self._fail_counts[agent_id] = 0
            if self._circuit_open.get(agent_id):
                self._circuit_open[agent_id] = False
            # V3/C2 : le process est vivant, mais l'agent avance-t-il ?
            stall = self._check_stall(agent_id)
            if stall:
                return stall
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

    def _oldest_parked_age(self, agent_id, now=None):
        """A8 : âge (s) de la plus ancienne entrée parquée non annexée.

        Le curseur d'annexation vit dans le hash agent (champ
        <stream>_cursor, écrit par _attach_pending_reports). Tout ce qui est
        au-delà du curseur n'a jamais été présenté au modèle.
        """
        now = time.time() if now is None else now
        worst = None
        worst_stream = ""
        cursors = {}
        try:
            cursors = self.redis.hgetall(f"agent:{agent_id}") or {}
        except Exception as exc:
            logger.warning("parked cursor read error for %s: %s",
                           agent_id, exc)
            return None, ""
        for suffix in PARKED_STREAM_SUFFIXES:
            stream = f"agent:{agent_id}:{suffix}"
            cursor = cursors.get(f"{suffix}_cursor", "") or "-"
            minimum = f"({cursor}" if cursor != "-" else "-"
            try:
                entries = self.redis.xrange(
                    stream, min=minimum, max="+", count=1)
            except Exception:
                continue
            if not entries:
                continue
            entry_id = str(entries[0][0])
            try:
                age = now - int(entry_id.split("-")[0]) / 1000.0
            except (ValueError, IndexError):
                continue
            if worst is None or age > worst:
                worst, worst_stream = age, suffix
        return worst, worst_stream

    def _check_unread(self, agent_id, now=None):
        """A8 : invariant de lecture — un message stocké finit par être lu.

        Deux angles : (1) entrées parquées jamais annexées au-delà de
        UNREAD_DEADLINE_S ; (2) inbox dont le consumer group traîne (lag ou
        PEL non vide) pendant plus que l'échéance — bridge mort ou bloqué.
        Une alerte par transition d'état ; le champ unread_backlog_s du hash
        agent expose la mesure au dashboard en continu.
        """
        now = time.time() if now is None else now
        worst, worst_stream = self._oldest_parked_age(agent_id, now)

        lag_age = 0.0
        try:
            groups = self.redis.xinfo_groups(f"agent:{agent_id}:inbox")
        except Exception:
            groups = []
        backlog = 0
        for group in groups or []:
            lag = group.get("lag")
            backlog += int(lag or 0) + int(group.get("pending") or 0)
        if backlog:
            first = self._inbox_lag_first_seen.setdefault(agent_id, now)
            lag_age = now - first
        else:
            self._inbox_lag_first_seen.pop(agent_id, None)

        try:
            self.redis.hset(f"agent:{agent_id}", mapping={
                "unread_backlog_s": int(worst or 0),
                "unread_backlog_stream": worst_stream,
                "inbox_lag_s": int(lag_age),
            })
        except Exception:
            pass

        breached = ((worst or 0) > UNREAD_DEADLINE_S
                    or lag_age > UNREAD_DEADLINE_S)
        if not breached:
            self._unread_alerted.pop(agent_id, None)
            return None
        if not self._unread_alerted.get(agent_id):
            self._unread_alerted[agent_id] = True
            details = {
                "oldest_parked_s": int(worst or 0),
                "parked_stream": worst_stream,
                "inbox_lag_s": int(lag_age),
                "deadline_s": UNREAD_DEADLINE_S,
            }
            self._publish_alert(
                "warning", agent_id,
                f"Agent {agent_id}: message stocké mais non lu depuis "
                f"{int(max(worst or 0, lag_age))}s "
                f"(échéance {UNREAD_DEADLINE_S}s)",
                details)
            wal.emit(
                self.redis, None, "unread_backlog", agent_id, None,
                **details)
        return "unread_backlog"

    def _check_stale_bridge(self, agent_id):
        """A8 : bridge longue durée exécutant un code plus vieux que le disque.

        Constat du 19/08 : bridge 334-134 chargé le 29/07 pendant que les
        correctifs des 18-19/08 attendaient sur disque — comportements
        asymétriques entre agents. Alerte seulement : le redémarrage reste
        une décision opérateur (./scripts/agent.sh reload-bridge <id>).
        """
        try:
            loaded = int(self.redis.hget(
                f"agent:{agent_id}", "bridge_code_mtime") or 0)
        except (TypeError, ValueError):
            loaded = 0
        except Exception as exc:
            logger.warning("stale bridge read error for %s: %s",
                           agent_id, exc)
            return None
        if not loaded:
            return None  # bridge antérieur à l'empreinte : rien à comparer
        disk = bridge_code_mtime_on_disk()
        if disk - loaded <= STALE_BRIDGE_GRACE_S:
            self._stale_alerted.pop(agent_id, None)
            return None
        if not self._stale_alerted.get(agent_id):
            self._stale_alerted[agent_id] = True
            self._publish_alert(
                "warning", agent_id,
                f"Agent {agent_id}: bridge chargé avec un code plus vieux "
                f"que le disque de {int(disk - loaded)}s — "
                f"./scripts/agent.sh reload-bridge {agent_id} pour appliquer",
                {"loaded_mtime": loaded, "disk_mtime": disk})
        return "stale_bridge"

    def run_cycle(self):
        """Exécute un cycle watchdog complet (EF-002)."""
        agents = self.discover_agents()
        results = self._check_obligations()
        now = time.time()
        for agent_id in agents:
            health_result = self.process_agent(agent_id)
            results.setdefault(agent_id, health_result)
            # A8 : invariants transverses, indépendants de l'état de santé.
            try:
                self._check_unread(agent_id, now)
            except Exception as exc:
                logger.warning("unread check error for %s: %s", agent_id, exc)
            try:
                self._check_stale_bridge(agent_id)
            except Exception as exc:
                logger.warning("stale bridge check error for %s: %s",
                               agent_id, exc)
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
