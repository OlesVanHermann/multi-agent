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
import uuid
from datetime import datetime
from threading import Thread, Lock
from queue import Queue, Empty
from enum import Enum
from collections import deque
from pathlib import Path

try:
    import redis
except ImportError:
    sys.stderr.write(
        "[agent-bridge] Dépendance manquante : le module Python 'redis' n'est pas installé.\n"
        "[agent-bridge] Installer les dépendances : pip install -r requirements.txt\n"
    )
    sys.exit(1)

# A6 : source unique du format d'ID agent
from ids import AGENT_ID_PATTERN, is_valid_agent_id

# V3/C1 : boucle verify — la complétion se prouve, ne se déclare pas
import verifier
# V3/C2 : write-ahead log d'orchestration (audit, stall detection, bench)
import wal
# Obligation durable créée par chaque DISPATCH corrélé.
import obligations
import event_router
from autoresponder import (
    AutoResponder, classify_active_dialog, selected_line_contains)

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "[agent-bridge] Dépendance manquante : le module Python 'yaml' (PyYAML) n'est pas installé.\n"
        "[agent-bridge] Installer les dépendances : pip install -r requirements.txt\n"
    )
    sys.exit(1)

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
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
MAX_HISTORY = 50
# Compatibilite de configuration : RESPONSE_TIMEOUT reste accepte mais ne
# borne plus la duree totale d'une tache. Il devient le seuil d'inactivite
# apres lequel le bridge signale STALLED sans publier de fausse reponse, sans
# XACK et sans passer au message suivant.
RESPONSE_STALL_THRESHOLD = int(os.environ.get(
    "RESPONSE_STALL_THRESHOLD", os.environ.get("RESPONSE_TIMEOUT", 300)))
# Alias conserve pour les integrations qui importent encore cette constante.
RESPONSE_TIMEOUT = RESPONSE_STALL_THRESHOLD
POLL_INTERVAL = 1.0
BUS_SCHEMA_VERSION = "ma.bus.v1"

# V3/C1 : boucle verify (opt-in par tâche via champ verify_cmd)
VERIFY_MAX_RETRIES = int(os.environ.get("VERIFY_MAX_RETRIES", 3))
PROJECT_DIR = os.environ.get("PROJECT_DIR", str(BASE_DIR / "project"))

# A2 : scrutation adaptative — intervalle court tant que le pane change,
# allongement progressif (×1.5) jusqu'au plafond dès stabilité.
POLL_MIN = float(os.environ.get("POLL_MIN", 0.2))
POLL_MAX = float(os.environ.get("POLL_MAX", 2.0))

# Durées de stabilité requises (en secondes) avant de conclure une réponse.
# Équivalentes aux anciens compteurs d'itérations à POLL_INTERVAL=1s.
# Surchargables par env (G1 : les tests E2E les raccourcissent).
STABLE_READY_SECS = float(os.environ.get("STABLE_READY_SECS", 5.0))
STABLE_FALLBACK_SECS = float(os.environ.get("STABLE_FALLBACK_SECS", 10.0))
STABLE_PLAN_SECS = float(os.environ.get("STABLE_PLAN_SECS", 15.0))

# Backoff entre deux tentatives après erreur API (G1 : raccourci en test)
RETRY_BACKOFF_SECS = float(os.environ.get("RETRY_BACKOFF_SECS", 10))


# Budget total de vérification de soumission d'Entrée dans _send_keys (s)
SEND_KEYS_BUDGET = 15.0


def _next_poll_interval(current, changed):
    """A2: prochain délai de poll — POLL_MIN si le pane a changé, sinon ×1.5 plafonné."""
    if changed:
        return POLL_MIN
    return min(current * 1.5, POLL_MAX)


def _composer_contains_text(viewport, cursor_y, snippet):
    """Return whether ``snippet`` is still in the active TUI composer.

    A long Codex/Claude prompt can wrap over many physical terminal rows and
    leave the cursor on an otherwise empty row. Looking at the cursor row alone
    therefore mistakes an unsubmitted prompt for an accepted one. The active
    composer is the nearest ``›``/``❯`` prompt at or above the cursor; inspect
    that complete block instead.

    If the composer cannot be identified, remain conservative: the caller must
    retry Enter rather than silently losing the task.
    """
    lines = viewport.splitlines()
    if not lines or not isinstance(cursor_y, int) or cursor_y < 0:
        return True
    cursor_y = min(cursor_y, len(lines) - 1)
    composer_start = None
    for idx in range(cursor_y, -1, -1):
        if lines[idx].lstrip().startswith(("›", "❯")):
            composer_start = idx
            break
    if composer_start is None:
        return True
    composer = " ".join(lines[composer_start:cursor_y + 1])
    return snippet in composer


def _plan_mode_active(out, markers):
    """Détecte uniquement l'indicateur actif, dans la zone UI récente.

    Une suggestion ou une ancienne occurrence dans le scrollback ne doit pas
    transformer l'état courant du TUI en mode plan.
    """
    scope = '\n'.join(out.splitlines()[-int(markers.get('plan_mode_tail_lines', 3)):])
    marker = markers['plan_mode']
    exclusions = markers.get('plan_mode_exclusions', [])
    required = markers.get('plan_mode_required', '')
    return any(line.lstrip().startswith(marker)
               and (not required or required in line)
               and not any(x in line for x in exclusions)
               for line in scope.splitlines())


def _configured_value(agent_id, extension, default=""):
    """Résout une configuration selon la cascade canonique, sans mutation."""
    return engines.resolve_agent_config(
        BASE_DIR / "prompts", str(agent_id), extension, default)


def _configured_model(agent_id):
    return _configured_value(agent_id, "model")


def _configured_effort(agent_id):
    return _configured_value(agent_id, "effort", "M")


def _expected_effort_name(effort):
    return {
        "L": "medium",
        "M": "high",
        "H": "xhigh",
        "X": "max",
        "U": "ultracode",
    }.get(
        str(effort).strip().upper(), str(effort).strip().lower())


def _normalize_model_name(model):
    value = re.sub(r'[^a-z0-9]+', '-', str(model).strip().lower()).strip('-')
    return value if value.startswith(('claude-', 'gpt-')) else f"claude-{value}"


def _runtime_value_from_pane(out, marker_key, markers=None):
    m = markers if markers is not None else MARKERS
    pattern = m.get(marker_key, '__NON_APPLICABLE__')
    if pattern == '__NON_APPLICABLE__':
        return ""
    matches = re.findall(pattern, out, re.MULTILINE)
    return matches[-1] if matches else ""


def _runtime_model_from_pane(out, markers=None):
    return _runtime_value_from_pane(out, 'runtime_model_pattern', markers)


def _runtime_effort_from_pane(out, markers=None):
    return _runtime_value_from_pane(out, 'runtime_effort_pattern', markers)

# EF-003 : intervalle heartbeat enrichi (CA-004: toutes les 10s ± 2s).
# Surcharge uniquement pour les tests E2E ; la production reste à 10 s.
HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", 10))
# EF-001 : port de base pour health endpoint (port = base + agent_id numérique)
HEALTH_PORT_BASE = int(os.environ.get("AGENT_HEALTH_PORT_BASE", 9100))

# A1 : marqueurs UI du CLI externalisés dans markers.<moteur>.yaml.
# E1 : le moteur est choisi par AGENT_CLI (claude par défaut) — engines.py
#      fait le chargement + la validation fail-fast. Aucune chaîne de rendu
#      CLI ne doit être codée en dur dans ce fichier.
import engines

AGENT_CLI = engines.current_engine()
_MARKERS_PATH = engines.markers_path(AGENT_CLI)
MARKERS = engines.load_markers(AGENT_CLI)

PROCESS_NAMES = MARKERS['process_names']
BUSY_SCOPE = MARKERS['busy_scope']
PROMPT_MARKERS = MARKERS['prompt_markers']
STATUS_LINE = MARKERS['status_line']
BUSY_MARKERS = MARKERS['busy_markers']
PLAN_MODE = MARKERS['plan_mode']
COMPACTION_IN_PROGRESS = MARKERS['compaction']['in_progress']
COMPACTION_DONE = MARKERS['compaction']['done']
APPROVAL_PROMPT = MARKERS['approval']
SURVEY_PROMPT = MARKERS['survey']
QUEUED_MSG = MARKERS['queued']
WAITING_SELECT = MARKERS['waiting_select']
CONTEXT_LIMIT = MARKERS['context_limit']
MODEL_CHANGE = MARKERS['model_change']
API_ERROR_MARKER = MARKERS['api_error']
SCROLL_INDICATOR = MARKERS['scroll_indicator']
BASHES_PATTERN = MARKERS['bashes_pattern']
CONTEXT_PCT_PATTERNS = MARKERS['context_pct_patterns']
API_ERROR_PATTERNS = MARKERS['api_error_patterns']

# CT-009 : borne streams monitoring
STREAM_MAXLEN = 1000

# A3 : borne streams métier (inbox/outbox) — évite la dérive mémoire Redis sur runs longs
IO_STREAM_MAXLEN = int(os.environ.get("IO_STREAM_MAXLEN", 10000))

# A8 : annexation avec échéance. Le non-réveil reste la règle, mais un contenu
# parqué (reports/control/terminals/supervision) ne peut plus attendre
# indéfiniment un « prochain vrai tour » qui n'arrive jamais : après
# ANNEX_FLUSH_IDLE_S d'inactivité, le bridge ouvre UN tour de synthèse borné
# qui annexe tout le backlog en une fois. ANNEX_FLUSH_MIN_INTERVAL_S plafonne
# la fréquence de ces tours (anti-bruit par groupage, pas par silence).
ANNEX_FLUSH_IDLE_S = float(os.environ.get("ANNEX_FLUSH_IDLE_S", 120))
ANNEX_FLUSH_MIN_INTERVAL_S = float(
    os.environ.get("ANNEX_FLUSH_MIN_INTERVAL_S", 300))
# A8 : accusés de lecture — DELIVERED décrit une écriture Redis, READ décrit
# un contenu réellement présenté au modèle. Clés ma:bus:v1:read:*.
READ_RECEIPT_TTL = int(os.environ.get("READ_RECEIPT_TTL", 604800))
# A8 : contexte d'enveloppe conservé après la fin du tour (champs last_*) pour
# les send.sh/done.sh/report-master.sh émis pendant le travail post-tour.
# A8 : texte visible dans le composer sans soumission pendant plus de
# COMPOSER_ORPHAN_S alors que l'agent est idle → alerte (jamais d'auto-submit).
COMPOSER_ORPHAN_S = float(os.environ.get("COMPOSER_ORPHAN_S", 300))


def _bridge_code_mtime(root=None):
    """Empreinte du code bridge présent sur disque : mtime max des sources.

    Publiée au démarrage dans le hash agent, elle permet au watchdog de
    détecter un bridge longue durée qui exécute un code plus vieux que celui
    sur disque (les correctifs Python ne s'appliquent qu'au redémarrage).
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


def _matches_api_error(text, patterns=None):
    """Détecte une erreur API à partir des regex propres au moteur."""
    candidates = API_ERROR_PATTERNS if patterns is None else patterns
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in candidates)


def _parse_pane_state(out, pane_cmd, agent_id, process_names=None, busy_scope=None,
                      markers=None):
    """B6 : déduit l'état d'un agent depuis le contenu de son pane tmux.

    Fonction pure (testable). Strictement équivalente au scan bash généré par
    engines.build_pane_eval() — la parité est PROUVÉE, champ par champ, par
    tests/test_pane_scan.py, pour les deux moteurs.

    E1 : tous les marqueurs viennent de `markers` (markers.<cli>.yaml). Défaut =
    ceux du moteur courant, pour que les appelants existants restent inchangés.
    `process_names` et `busy_scope` restent surchargeables séparément (rétro-
    compat des tests). La clé de sortie reste 'claude_alive' : c'est le contrat
    du cache dashboard, elle n'est pas renommée.
    """
    m = markers if markers is not None else MARKERS
    if process_names is None:
        process_names = m['process_names']
    if busy_scope is None:
        busy_scope = m['busy_scope']

    busy_markers = m['busy_markers']

    claude_alive = pane_cmd in tuple(process_names)
    lines = out.split('\n')
    login_required = any(marker.lower() in out.lower()
                         for marker in m['login_expired_markers'])

    bp_line = ""
    for line in lines:
        if m['status_line'] in line:
            bp_line = line

    if m['bashes_scope'] == 'status_line':
        has_bashes = bool(re.search(m['bashes_pattern'], bp_line))
    else:
        has_bashes = bool(re.search(m['bashes_pattern'], '\n'.join(lines[-20:])))

    if not claude_alive or login_required:
        busy = False
    elif busy_scope == 'status_line':
        # Claude Code : l'indice « esc to interrupt » est DANS la ligne de statut.
        # Le prompt ❯ peut rester visible pendant que des sous-agents tournent :
        # sa présence ne prouve rien. Seule la ligne de statut fait foi.
        if any(x in bp_line for x in busy_markers):
            busy = True
        elif bp_line:
            busy = False
        else:
            busy = True
    else:
        # Codex : l'indicateur d'activité est un widget SÉPARÉ, au-dessus du
        # composer — et le composer « › » reste affiché pendant le travail.
        # L'heuristique ci-dessus conclurait TOUJOURS idle.
        tail = '\n'.join(lines[-20:])
        busy = bool(re.search('|'.join(busy_markers), tail))

    done_compacting = bool(re.search(re.escape(m['compaction']['done']), out, re.IGNORECASE))
    pid = str(agent_id).split('-')[0]
    prompt_loaded = bool(done_compacting and re.search(
        r'prompts/' + re.escape(pid) + r'[^ ]*/' + re.escape(str(agent_id)) + r'[.-]'
        r'|prompts/' + re.escape(str(agent_id)) + r'-', out))

    ctx = -1
    ctx_matches = re.findall('|'.join(m['context_pct_patterns']), out)
    if ctx_matches:
        nums = re.findall(r'[0-9]+', ctx_matches[-1])
        if nums:
            ctx = int(nums[-1])

    return {
        'busy': busy,
        'has_bashes': has_bashes,
        'has_down': m['scroll_indicator'] in bp_line,
        'plan_mode': _plan_mode_active(out, m),
        'waiting_approval': m['waiting_select'] in out,
        'login_required': login_required,
        'compacted': bool(re.search(re.escape(m['compaction']['in_progress']), out, re.IGNORECASE)),
        'context_pct': ctx,
        'done_compacting': done_compacting,
        'prompt_loaded': prompt_loaded,
        'context_limit': m['context_limit'] in out,
        'api_error': (
            _matches_api_error(out, m['api_error_immediate_patterns'])
            or out.count(m['api_error']) >= 3
            or (claude_alive and not bp_line)
        ),
        'model_change': m['model_change'] in out,
        'claude_alive': claude_alive,
    }


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    """Health endpoint HTTP — EF-001, CT-001 (http.server stdlib).

    Retourne JSON avec 6 champs requis (CA-001: <500ms).
    Auth: static token from HEALTH_TOKEN env var (query param or Bearer header).
    """
    agent_ref = None  # Set by _start_health_server
    health_token = None  # Set by _start_health_server

    def _check_auth(self):
        token = self.__class__.health_token
        if not token:
            return False  # no token configured = reject all (secure by default)
        # Check query param ?token=
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        if qs.get('token', [None])[0] == token:
            return True
        # Check Bearer header
        auth = self.headers.get('Authorization', '')
        if auth == f'Bearer {token}':
            return True
        return False

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/health':
            if not self._check_auth():
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"detail":"Authentication required"}')
                return
            agent = self.__class__.agent_ref
            if not agent:
                self.send_response(503)
                self.end_headers()
                return
            try:
                redis_ok = agent._redis_ping()
            except Exception:
                redis_ok = False
            listeners = agent._listener_health_snapshot()
            if not isinstance(listeners, dict):
                listeners = {}
            data = {
                "status": "healthy" if (
                    redis_ok and agent._consumers_healthy()) else "degraded",
                "agent_id": agent.agent_id,
                "uptime_seconds": int(time.time() - agent._start_time),
                "last_heartbeat_ts": getattr(agent, '_last_heartbeat_ts', 0),
                "redis_connected": redis_ok,
                "pty_active": agent._tmux_session_exists(),
                "auth_blocked": bool(
                    getattr(agent, "_auth_blocked", False)),
                "listeners": listeners,
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
        self.session_name = f"agent-{agent_id}"
        self.state = State.IDLE
        self.state_lock = Lock()
        self._tui_lock = Lock()
        auto_config = MARKERS["auto_response"]
        self._auto_responder = AutoResponder(
            cooldown_seconds=auto_config["cooldown_seconds"],
            max_attempts=auto_config["max_attempts"],
        )
        # L'état du modèle est observé passivement. Une slash-command sans
        # argument ouvre un picker interactif et bloquerait le TUI.
        self._observed_model = ""
        self._observed_effort = ""
        self._auth_blocked = False

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

        # A5 (fix re-injection 11/07) : ids inbox en vol — un message Redis
        # deja mis en queue ne doit JAMAIS y retourner tant qu'il n'est pas
        # XACK (une injection = un ack). Protege contre toute re-livraison
        # (drain pending, XAUTOCLAIM futur, bug de boucle).
        self._inflight_ids = set()
        self._inflight_lock = Lock()

        # A6 (fix ordonnancement 16/07) : les pending recovery du listener
        # Redis partaient dans la queue AVANT le « deviens agent » d'auto-load
        # (run()) — l'agent recevait sa tâche avant son identité. Le listener
        # attend cet évènement, posé par run() une fois l'auto-init en queue.
        self._auto_init_queued = threading.Event()

        # A8 : annexation avec échéance — horloge d'inactivité et plafond de
        # fréquence des tours de synthèse.
        self._last_turn_end_ts = time.time()
        self._last_flush_ts = 0.0
        # A8 : détection de composer orphelin (texte saisi, jamais soumis).
        self._composer_orphan = {"text": "", "since": 0.0, "alerted": False}

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
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)
        self.inbox = f"agent:{agent_id}:inbox"
        self.outbox = f"agent:{agent_id}:outbox"
        # A4: consumer group — survives bridge restarts (no lost/replayed messages)
        self.group = "bridge"
        self.consumer = f"agent-{agent_id}"

        try:
            self.redis.ping()
        except redis.ConnectionError:
            self._log(f"ERROR: Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}")
            sys.exit(1)

        # R-INTEGRATE: MetricsCollector pour tracking performance
        try:
            from monitoring.metrics_collector import MetricsCollector
            self.metrics = MetricsCollector(self.redis)
            self._log("MetricsCollector initialized (R-INTEGRATE)")
        except ImportError:
            self.metrics = None
            self._log("WARNING: monitoring.metrics_collector not available")

        # A8 : publier l'empreinte du code chargé — le watchdog compare avec
        # le disque et signale STALE_BRIDGE quand un correctif attend un reload.
        try:
            self.redis.hset(f"agent:{self.agent_id}", mapping={
                "bridge_code_mtime": _bridge_code_mtime(),
                "bridge_started_at": int(self._start_time),
                "bridge_pid": os.getpid(),
            })
        except Exception as e:
            self._log(f"Bridge fingerprint publish error: {e}")

        # V3/C2 : diagnostic post-crash — tâche restée ouverte dans le WAL.
        # Log seulement : le consumer group redélivre le message pending (A4).
        try:
            pending_task = wal.open_task(self.redis, None, self.agent_id)
            if pending_task:
                self._log(f"WAL: tâche ouverte au démarrage: {pending_task} "
                          "(redélivrance via consumer group)")
        except Exception as e:
            self._log(f"WAL open_task check error: {e}")

        # Get initial pane content to know baseline
        self.last_output_lines = self._get_pane_line_count()

        # Legacy inbox (A:inject:{id} format used by prompts)
        self.legacy_inbox = f"inject:{agent_id}"

        # Threads
        self.running = True
        self._listener_health_lock = Lock()
        self._listener_health = {
            name: {
                "state": "starting",
                "last_ok_ts": 0,
                "last_error_ts": 0,
                "last_error": "",
            }
            for name in ("redis_listener", "legacy_listener", "heartbeat")
        }
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
        self.health_port = 0
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

    def _wal(self, wal_event, task_id=None, **fields):
        """V3/C2 : émission WAL best-effort — une panne Redis sur le WAL
        ne doit JAMAIS tuer le thread queue_processor."""
        try:
            wal.emit(self.redis, None, wal_event, self.agent_id,
                     task_id, **fields)
        except Exception as e:
            self._log(f"WAL emit error ({wal_event}): {e}")

    def _listener_health_snapshot(self):
        """Return a copy of listener health without depending on Redis."""
        lock = getattr(self, "_listener_health_lock", None)
        health = getattr(self, "_listener_health", {})
        if lock is None:
            return dict(health)
        with lock:
            return {
                name: dict(values)
                for name, values in health.items()
            }

    def _set_listener_health(self, name, state, error=""):
        """Track listener liveness locally; Redis publication is best effort."""
        now = int(time.time())
        lock = getattr(self, "_listener_health_lock", None)
        health = getattr(self, "_listener_health", None)
        if health is None:
            health = {}
            self._listener_health = health
        values = dict(health.get(name, {}))
        values["state"] = state
        if state == "up":
            values["last_ok_ts"] = now
            values["last_error"] = ""
        elif error:
            values["last_error_ts"] = now
            values["last_error"] = str(error)[:500]
        if lock is None:
            health[name] = values
        else:
            with lock:
                health[name] = values
        try:
            self.redis.hset(
                f"agent:{self.agent_id}",
                mapping={
                    "listener_health": json.dumps(
                        self._listener_health_snapshot(), sort_keys=True),
                    "consumer_state": (
                        "up" if self._consumers_healthy() else "degraded"),
                })
        except Exception:
            # Redis can be the failing component. Local state and the HTTP
            # health endpoint must remain usable in that case.
            pass

    def _consumers_healthy(self):
        health = self._listener_health_snapshot()
        return bool(health) and all(
            health.get(name, {}).get("state") == "up"
            for name in ("redis_listener", "legacy_listener"))

    def _record_metrics_error(self, exc):
        """Metrics are observability only and must never kill a listener."""
        if not getattr(self, "metrics", None):
            return
        try:
            self.metrics.record_error(
                self.agent_id, type(exc).__name__, str(exc))
        except Exception as metrics_exc:
            self._log(f"Metrics error ignored: {metrics_exc}")

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

    def _capture_dialog_context(self):
        """Capture le viewport actif et le process juste avant une interaction."""

        target = f"{self.session_name}:0.0"
        try:
            pane = subprocess.run(
                ["tmux", "capture-pane", "-t", target, "-p", "-J"],
                capture_output=True, text=True, timeout=5)
            command = subprocess.run(
                ["tmux", "display-message", "-t", target, "-p",
                 "#{pane_current_command}"],
                capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            self._log(f"AUTO-RESPONSE capture failed: {exc}")
            return "", ""
        if pane.returncode != 0 or command.returncode != 0:
            return "", ""
        return pane.stdout, command.stdout.strip()

    def _get_auto_responder(self):
        """Initialisation paresseuse pour les tests qui construisent via __new__."""

        responder = getattr(self, "_auto_responder", None)
        if responder is None:
            config = MARKERS["auto_response"]
            responder = AutoResponder(
                cooldown_seconds=config["cooldown_seconds"],
                max_attempts=config["max_attempts"],
            )
            self._auto_responder = responder
        return responder

    def _send_dialog_keys(self, keys):
        """Envoie une réponse de modale, sans toucher au composer.

        Contrairement à _send_keys(), cette méthode n'envoie ni C-u, ni
        collage, ni retry d'Enter. La séquence validée part dans un unique
        appel tmux afin de ne jamais dupliquer un choix.
        """

        keys = tuple(str(key) for key in keys)
        # A10 : chiffres de sélection des dialogues déclarés + Escape de repli.
        # Toute touche hors de cette liste reste refusée.
        allowed = {"0", "1", "2", "3", "4", "5", "Enter", "Escape"}
        if not keys or any(key not in allowed for key in keys):
            raise ValueError("unsafe auto-response key sequence")
        target = f"{self.session_name}:0.0"
        try:
            result = subprocess.run(
                ["tmux", "send-keys", "-t", target, *keys],
                capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            self._log(f"AUTO-RESPONSE tmux failure: {exc}")
            return False
        if result.returncode != 0:
            self._log(
                "AUTO-RESPONSE tmux rejected keys "
                f"(rc={result.returncode})")
            return False
        return True

    def _composer_text_of(self, pane_text):
        """Texte du composer actif ; '' si aucun composer actif.

        Le composer vit structurellement au BAS du TUI : seules les
        dernières lignes non vides comptent — un « ❯ ancien message » du
        scrollback n'est pas un composer occupé. Une ligne « › 2. Switch… »
        est une OPTION sélectionnée de dialogue, pas un composer : une
        option numérotée est ignorée.
        """
        lines = [
            line for line in str(pane_text or "").splitlines()
            if line.strip()
        ]
        for line in reversed(lines[-3:]):
            stripped = line.lstrip()
            if not stripped.startswith(("›", "❯")):
                continue
            remainder = stripped[1:].strip()
            if re.match(r"^[0-9]+[.):]\s", remainder):
                continue
            return remainder
        return ""

    def _persisted_attempts_exceeded(self, decision):
        """A10 : le budget de tentatives survit au restart du bridge.

        Le compteur mémoire de AutoResponder repart à zéro à chaque
        redémarrage ; la même empreinte récidivante repartait donc pour
        max_attempts frappes. Fail-open : une panne Redis ne bloque jamais
        la réponse (le compteur mémoire reste la borne de session).
        """
        try:
            key = f"autoresp:{self.agent_id}:{decision.fingerprint}"
            count = int(self.redis.incr(key))
            self.redis.expire(key, 3600)
            return count > int(
                MARKERS["auto_response"].get("max_attempts", 3))
        except Exception:
            return False

    def _publish_dialog_alert(self, decision, detail):
        try:
            self.redis.xadd("monitoring:alerts", {
                "from": "bridge",
                "type": "alert:warning",
                "agent_id": self.agent_id,
                "message": (
                    f"Agent {self.agent_id}: auto-réponse "
                    f"{decision.kind} — {detail}"),
                "timestamp": str(int(time.time())),
                "payload": json.dumps(
                    {"fingerprint": decision.fingerprint}),
            }, maxlen=STREAM_MAXLEN, approximate=True)
        except Exception as exc:
            self._log(f"AUTO-RESPONSE alert publish failed: {exc}")

    def _maybe_auto_respond(self, pane_text, pane_command, source):
        """Répond à un dialogue complet après une seconde capture TOCTOU."""

        responder = self._get_auto_responder()
        decision = classify_active_dialog(
            pane_text, pane_command, MARKERS)
        if decision is None:
            responder.reset_when_absent()
            return False

        # Le navigateur ou l'opérateur peut répondre entre la première capture
        # et ici. Revalider process, dialogue et empreinte juste avant la frappe.
        verified_pane, verified_command = self._capture_dialog_context()
        verified = classify_active_dialog(
            verified_pane, verified_command, MARKERS)
        if verified is None or verified.fingerprint != decision.fingerprint:
            if verified is None:
                responder.reset_when_absent()
            return True
        decision = verified

        # A10/EF-A1 : un composer occupé signifie qu'une frappe (opérateur ou
        # séquence précédente) est en cours — toute touche émise maintenant
        # risque d'y atterrir et de partir comme message. Abandon propre.
        if self._composer_text_of(verified_pane):
            self._log(
                f"AUTO-RESPONSE aborted (composer busy) kind={decision.kind}")
            return True

        if not responder.observe(decision):
            return True

        # A10 : budget d'empreinte persistant (survit au restart du bridge).
        if self._persisted_attempts_exceeded(decision):
            self._log(
                "AUTO-RESPONSE suppressed (persistent attempt budget) "
                f"kind={decision.kind} fingerprint={decision.fingerprint}")
            responder.mark_failed(decision)
            return True

        attempt = responder.attempts
        self._log(
            "AUTO-RESPONSE "
            f"kind={decision.kind} source={source} attempt={attempt}/"
            f"{MARKERS['auto_response']['max_attempts']} "
            f"fingerprint={decision.fingerprint}")
        self._log_event(
            "auto_response",
            f"kind={decision.kind} source={source} attempt={attempt} "
            f"fingerprint={decision.fingerprint}")
        try:
            self.redis.hset(
                f"agent:{self.agent_id}", "status", "waiting_approval")
        except Exception:
            pass

        try:
            sent = self._send_dialog_keys(decision.keys)
        except Exception as exc:
            self._log(f"AUTO-RESPONSE refused: {exc}")
            sent = False
        # A10/EF-A2 : si les touches ont atterri dans le composer (dialogue
        # fermé entre la vérification et la frappe), les retirer — c'est le
        # bug du « 0 » fantôme soumis comme message (constat 06/09, 334-834).
        if sent and self._revert_leaked_dialog_keys(decision):
            sent = False
        elif sent and decision.confirm_key:
            # A10 : confirmation en deux temps — preuve de sélection exigée.
            sent = self._confirm_dialog_selection(decision)
        if sent:
            responder.mark_applied(decision)
        else:
            responder.mark_failed(decision)
            self._log_event(
                "auto_response_failed",
                f"kind={decision.kind} source={source} attempt={attempt}")
        self._set_redis_status()
        return True

    def _confirm_dialog_selection(self, decision):
        """A10 : n'émettre la confirmation qu'avec la preuve de sélection.

        Après la frappe de sélection : dialogue disparu = le chiffre a
        sélectionné-confirmé (pickers instantanés) → succès ; dialogue
        présent avec la ligne ›/❯ sur l'option décidée → confirm_key ;
        sinon → Escape + alerte. Un Enter à l'aveugle validerait l'option
        surlignée par défaut — qui peut être une bascule de modèle.
        """
        pane, command = self._capture_dialog_context()
        current = classify_active_dialog(pane, command, MARKERS)
        if current is None or current.fingerprint != decision.fingerprint:
            return True
        config = MARKERS.get("auto_response") or {}
        if decision.confirm_selected and not selected_line_contains(
                pane, config, decision.confirm_selected):
            self._log(
                "AUTO-RESPONSE escape — selection not on "
                f"'{decision.confirm_selected}' (kind={decision.kind})")
            self._publish_dialog_alert(
                decision, "sélection non confirmée, Escape émis")
            try:
                self._send_dialog_keys(("Escape",))
            except Exception as exc:
                self._log(f"AUTO-RESPONSE escape failed: {exc}")
            return False
        try:
            return self._send_dialog_keys((decision.confirm_key,))
        except Exception as exc:
            self._log(f"AUTO-RESPONSE confirm refused: {exc}")
            return False

    def _revert_leaked_dialog_keys(self, decision):
        """A10/EF-A2 : retirer une séquence tombée dans le composer.

        Ne nettoie (C-u) que si le composer contient EXACTEMENT les chiffres
        émis — jamais un texte d'opérateur ou d'agent.
        """
        typed = "".join(
            key for key in decision.keys if len(key) == 1 and key.isdigit())
        if not typed:
            return False
        pane, command = self._capture_dialog_context()
        # Dialogue encore affiché (même empreinte) = la frappe est un écho de
        # saisie en cours de consommation par le dialogue — un C-u ici
        # effacerait une réponse légitime. Le revert n'est autorisé que si le
        # dialogue a DISPARU et que le composer porte exactement la séquence.
        current = classify_active_dialog(pane, command, MARKERS)
        if current is not None and current.fingerprint == decision.fingerprint:
            return False
        if self._composer_text_of(pane) != typed:
            return False
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", f"{self.session_name}:0.0", "C-u"],
                capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            self._log(f"AUTO-RESPONSE revert failed: {exc}")
        self._log(
            "AUTO-RESPONSE reverted — keys landed in composer "
            f"(kind={decision.kind})")
        self._log_event("auto_response_reverted", decision.kind)
        return True

    def _auto_respond_while_idle(self, pane_text, pane_command):
        """Chemin permanent : agit uniquement si le queue processor est idle."""

        with self.state_lock:
            if self.state != State.IDLE:
                return False

        decision = classify_active_dialog(
            pane_text, pane_command, MARKERS)
        if decision is None:
            self._get_auto_responder().reset_when_absent()
            return False

        # Ne jamais attendre le TUI : pendant un tour, _wait_for_response est
        # l'unique propriétaire et détient déjà ce verrou.
        if not self._tui_lock.acquire(blocking=False):
            return False
        try:
            with self.state_lock:
                if self.state != State.IDLE:
                    return False
            return self._maybe_auto_respond(
                pane_text, pane_command, source="heartbeat-idle")
        finally:
            self._tui_lock.release()

    def _send_keys(self, text):
        """Send keys to tmux pane 0 (where Claude runs).

        NOTE: No Ctrl-C — it would interrupt Claude's thinking/execution.
        Ctrl-U clears the input line safely without interrupting.

        Le texte transite par stdin + buffer tmux, jamais comme argument de
        ``send-keys -l``. Cela évite ARG_MAX et garantit un collage atomique en
        mode bracketed-paste pour les prompts longs/multilignes. Les lignes
        vides externes sont retirées : elles n'ont pas de valeur métier et une
        fin composée uniquement de retours ligne peut empêcher certains TUI de
        considérer l'Enter suivant comme une soumission.
        """
        target = f"{self.session_name}:0"

        text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not text:
            self._log("Empty prompt after newline normalization — not submitted")
            return

        subprocess.run(["tmux", "send-keys", "-t", target, "C-u"], capture_output=True)
        time.sleep(0.3)

        buffer_name = f"ma-{self.agent_id}-{threading.get_ident()}-{time.time_ns()}"
        loaded = subprocess.run(
            ["tmux", "load-buffer", "-b", buffer_name, "-"],
            input=text, text=True, capture_output=True
        )
        if loaded.returncode != 0:
            raise RuntimeError(f"tmux load-buffer failed: {loaded.stderr.strip()}")
        pasted = subprocess.run(
            ["tmux", "paste-buffer", "-p", "-d", "-b", buffer_name, "-t", target],
            capture_output=True, text=True
        )
        if pasted.returncode != 0:
            subprocess.run(["tmux", "delete-buffer", "-b", buffer_name], capture_output=True)
            raise RuntimeError(f"tmux paste-buffer failed: {pasted.stderr.strip()}")
        time.sleep(1)

        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            capture_output=True
        )

        # Verify Enter was submitted by checking the complete active composer.
        # A wrapped prompt may leave the cursor on an empty physical row: the
        # cursor row alone then produces a false positive (task not submitted).
        # A2: adaptive loop — exit as soon as the input line is clear,
        # resend Enter on an escalating cadence (1/2/4/8s), same ~15s budget.
        target_pane = f"{self.session_name}:0"
        # cursor_y est relatif au viewport tmux, pas au scrollback. Vérifier la
        # fin du texte (située près du curseur même quand le composer replie un
        # long message), dans une capture du viewport uniquement.
        visible_tail = ' '.join(text.rstrip().splitlines()[-2:]).strip()
        check_snippet = visible_tail[-16:] if len(visible_tail) > 16 else visible_tail
        deadline = time.time() + SEND_KEYS_BUDGET
        resend_delay = 1.0
        next_resend = time.time() + resend_delay
        poll = POLL_MIN
        while time.time() < deadline:
            time.sleep(poll)
            try:
                cy = subprocess.run(
                    ["tmux", "display-message", "-t", target_pane, "-p", "#{cursor_y}"],
                    capture_output=True, text=True
                ).stdout.strip()
                viewport = subprocess.run(
                    ["tmux", "capture-pane", "-t", target_pane, "-p"],
                    capture_output=True, text=True
                ).stdout
                cursor_y = int(cy) if cy.isdigit() else -1
            except Exception:
                viewport = ''
                cursor_y = -1
            if not _composer_contains_text(viewport, cursor_y, check_snippet):
                break  # submitted (text no longer in the active composer)
            if time.time() >= next_resend:
                self._log(f"Enter not received after {resend_delay:.0f}s — resending")
                subprocess.run(
                    ["tmux", "send-keys", "-t", target, "Enter"],
                    capture_output=True
                )
                resend_delay = min(resend_delay * 2, 8.0)
                next_resend = time.time() + resend_delay
            poll = _next_poll_interval(poll, False)

    # Sentinel returned by _wait_for_response when compaction is detected
    _COMPACTION_SENTINEL = "__COMPACTION_DETECTED__"

    def _wait_for_response(self, timeout=None, baseline=None):
        """Attend une completion certaine, sans deadline murale.

        ``timeout`` est conserve uniquement comme seuil de stall pour les
        appels historiques/tests. Un stall est diagnostique dans Redis mais ne
        devient jamais une reponse canonique et ne libere jamais la FIFO.
        """
        stall_threshold = RESPONSE_STALL_THRESHOLD if timeout is None else timeout
        if baseline is None:
            baseline = self._capture_pane(200)
        baseline_hash = hash(baseline)
        baseline_compaction_count = baseline.count(COMPACTION_DONE)

        last_content = ""
        tail3_stable_since = time.time()
        response_started = False
        last_printed = 0
        poll = POLL_MIN
        queued_logged = False
        last_activity_at = time.time()
        stalled_logged = False
        last_observed_content = baseline

        while getattr(self, 'running', True):
            time.sleep(poll)

            current = self._capture_pane(200)
            pane_changed = current != last_observed_content
            if pane_changed:
                last_activity_at = time.time()
                last_observed_content = current
                if stalled_logged:
                    self._log("STALL CLEARED — terminal activity resumed")
                    stalled_logged = False
                    try:
                        self.redis.hset(
                            f"agent:{self.agent_id}",
                            "status", "busy")
                    except Exception:
                        pass
            # A2: poll court tant que le pane change, allongé dès stabilité
            poll = _next_poll_interval(poll, pane_changed)

            # Une absence d'activite est un diagnostic, jamais une completion.
            # La tache reste courante et son entree Redis reste pending.
            if (stall_threshold and not stalled_logged
                    and time.time() - last_activity_at >= stall_threshold):
                self._log(
                    f"STALL DETECTED — no terminal activity for {stall_threshold}s; "
                    "task remains pending")
                self._log_event("stall", f"inactive_for={stall_threshold}")
                self._wal("stall", (getattr(self, 'current_task', None) or {}).get('task_id'),
                          inactive_for=stall_threshold)
                try:
                    self.redis.hset(
                        f"agent:{self.agent_id}",
                        "status", "stalled")
                except Exception:
                    pass
                stalled_logged = True

            # Detect queued message (Claude busy, prompt queued by the TUI).
            # A5 : NE PAS retourner — l'ancien code renvoyait le pane comme
            # "reponse" (publiee + ack) pendant que la TUI gardait le prompt
            # en file ; combine aux re-livraisons, ca floodait la TUI. Le
            # prompt EST pris en compte (file TUI) : on attend l'idle, la TUI
            # le soumettra elle-meme ; un stall est signale sans abandon.
            if QUEUED_MSG in current:
                if not queued_logged:
                    self._log("QUEUED MESSAGE detected — Claude busy, waiting for idle (no re-send)")
                    queued_logged = True
                continue

            # Dialogues interactifs : ce chemin détient déjà _tui_lock pour
            # toute la durée du tour. Le heartbeat n'intervient donc pas ici.
            # Une pré-détection bornée évite deux appels tmux à chaque poll.
            dialog_tail_lines = int(
                MARKERS["auto_response"].get("tail_lines", 30))
            dialog_lines = current.splitlines()
            while dialog_lines and not dialog_lines[-1].strip():
                dialog_lines.pop()
            dialog_tail = "\n".join(dialog_lines[-dialog_tail_lines:])
            dialog_markers = (
                APPROVAL_PROMPT, SURVEY_PROMPT, WAITING_SELECT)
            dialog_hint = any(
                marker and marker in dialog_tail
                for marker in dialog_markers)
            if dialog_hint:
                dialog_pane, dialog_command = self._capture_dialog_context()
                if self._maybe_auto_respond(
                        dialog_pane, dialog_command, source="active-turn"):
                    # Le dialogue (déjà répondu ou dédupliqué) n'est jamais
                    # une completion de la réponse métier.
                    last_content = ""
                    tail3_stable_since = time.time()
                    last_printed = 0
                    poll = POLL_MIN
                    continue
            else:
                self._get_auto_responder().reset_when_absent()

            # Un overlay d'approbation incomplet/inconnu reste visible au
            # dashboard, mais aucune touche n'est inventée.
            if APPROVAL_PROMPT in dialog_tail:
                try:
                    self.redis.hset(
                        f"agent:{self.agent_id}",
                        "status", "waiting_approval")
                except Exception:
                    pass

            # Detect context compaction — only if NEW (more occurrences than baseline)
            if current.count(COMPACTION_DONE) > baseline_compaction_count:
                self._log("COMPACTION DETECTED in tmux output")
                # Wait for Claude to finish compacting and show prompt
                for _ in range(30):
                    time.sleep(POLL_INTERVAL)
                    current = self._capture_pane(200)
                    current_lines = current.strip().split('\n')
                    last_line = current_lines[-1].strip() if current_lines else ""
                    for marker in PROMPT_MARKERS:
                        if last_line.endswith(marker) or last_line == marker:
                            return self._COMPACTION_SENTINEL
                return self._COMPACTION_SENTINEL

            if current != last_content:
                last_content = current
                if hash(current) != baseline_hash:
                    response_started = True

                current_lines = current.strip().split('\n')
                if len(current_lines) > last_printed:
                    for line in current_lines[last_printed:][-5:]:
                        if line.strip():
                            print(f"  {line}", flush=True)
                    last_printed = len(current_lines)

            # Check if Claude is at a ready prompt (last non-empty lines show known status)
            # status_line = normal mode → ready
            # plan_mode = plan mode → ready only after extended stability
            non_empty = [l for l in current.split('\n') if l.strip()]
            tail3 = ' '.join(non_empty[-3:])

            # Stability based on prompt area only (last 3 non-empty lines)
            # Background bashes and spinners change upper content but prompt area stays stable
            # A2: stabilité mesurée en secondes (équivalent des anciens compteurs à 1s/poll)
            tail3_key = tail3
            if tail3_key != getattr(self, '_last_tail3_key', ''):
                self._last_tail3_key = tail3_key
                tail3_stable_since = time.time()
            stable_secs = time.time() - tail3_stable_since

            at_normal_prompt = STATUS_LINE in tail3 or (
                _plan_mode_active(current, MARKERS) and stable_secs >= STABLE_PLAN_SECS)

            current_lines = current.strip().split('\n')
            last_line = current_lines[-1].strip() if current_lines else ""

            if at_normal_prompt:
                # Check prompt marker on last line OR last few non-empty lines
                # (status bar with bashes count may be below the prompt marker)
                has_marker = False
                for marker in PROMPT_MARKERS:
                    if last_line.endswith(marker) or last_line == marker:
                        has_marker = True
                        break
                if not has_marker:
                    for line in non_empty[-3:]:
                        stripped = line.strip()
                        for marker in PROMPT_MARKERS:
                            if stripped == marker:
                                has_marker = True
                                break
                        if has_marker:
                            break

                if has_marker and response_started and stable_secs >= STABLE_READY_SECS:
                    response = '\n'.join(current_lines[:-1]).strip()
                    return response

                if stable_secs > STABLE_FALLBACK_SECS and response_started:
                    response = '\n'.join(current_lines).strip()
                    for marker in PROMPT_MARKERS:
                        if response.endswith(marker):
                            response = response[:-len(marker)].strip()
                    return response

        # Arret explicite du bridge uniquement. Le caller ne doit pas publier
        # cette sentinelle comme une completion de la tache.
        return "__BRIDGE_STOPPED__"

    def _run_claude(self, prompt):
        """Send prompt to Claude via tmux and capture response"""
        self._log(f"Sending to Claude: {prompt[:60]}...")
        self._log_event("prompt", prompt[:120])

        print(f"\n{'─'*60}", flush=True)
        print(f"📤 CLAUDE (tmux interactive):", flush=True)
        print(f"{'─'*60}", flush=True)

        # Prendre le baseline avant l'envoi : un TUI factice ou très rapide peut
        # produire sa réponse avant le retour de _send_keys().
        response_baseline = self._capture_pane(200)
        self._send_keys(prompt)

        # Append prompt to .history file (like a user typing in the terminal)
        try:
            prompt_path = self._find_prompt_file()
            if prompt_path:
                history_file = Path(prompt_path).parent / f"{self.agent_id}.history"
                from datetime import datetime
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(history_file, 'a') as hf:
                    hf.write(f"{ts} | {prompt}\n")
        except Exception as e:
            self._log(f"History append failed: {e}")

        response = self._wait_for_response(baseline=response_baseline)

        print(f"{'─'*60}\n", flush=True)

        return response

    def _set_redis_status(self):
        """Update status in Redis"""
        try:
            self.redis.hset(f"agent:{self.agent_id}", mapping={
                "status": self.state.value,
                "last_seen": int(time.time()),
                "queue_size": self.prompt_queue.qsize(),
                "tasks_completed": self.tasks_completed,
                "messages_since_reload": self.messages_since_reload,
                "mode": "tmux-interactive",
                "health_port": getattr(self, "health_port", 0),
                "health_pid": os.getpid(),
                "health_started_at": int(getattr(self, "_start_time", 0)),
                # Capability du consumer, indépendante du schéma d'une tâche.
                "bus_schema_version": BUS_SCHEMA_VERSION,
            })
        except redis.ConnectionError:
            pass

    def _start_health_server(self):
        """Démarre le serveur HTTP health endpoint — EF-001, CT-001.

        Le noyau attribue un port libre. Le port réellement lié est publié
        dans le hash Redis de l'agent pour éviter toute collision entre un
        agent global (334) et un agent de triangle (334-134).
        """
        health_token = os.environ.get('HEALTH_TOKEN', '')
        handler_class = type('Handler', (_HealthHandler,), {'agent_ref': self, 'health_token': health_token})
        try:
            server = http.server.HTTPServer(('127.0.0.1', 0), handler_class)
            server.timeout = 1
            self._health_server = server
            self.health_port = int(server.server_address[1])
            t = Thread(target=self._health_serve_loop, daemon=True, name="health_server")
            t.start()
            self._log(
                f"Health endpoint started on port {self.health_port} (EF-001)")
        except OSError as e:
            self.health_port = 0
            self._log(f"WARNING: Health server unavailable: {e}")

    def _health_serve_loop(self):
        """Boucle du serveur health — EF-001."""
        while self.running and self._health_server:
            try:
                self._health_server.handle_request()
            except Exception:
                pass

    def _derive_pane_state(self):
        """B6: capture this agent's pane once and derive its dashboard state.

        Runs in the bridge (1 process per agent) so the dashboard reads the
        result from Redis instead of forking a multi-grep scan per cycle.
        """
        target = f"{self.session_name}:0.0"
        self._last_pane_snapshot = None
        try:
            out = subprocess.run(
                ["tmux", "capture-pane", "-t", target, "-p", "-J", "-S", "-30"],
                capture_output=True, text=True, timeout=10).stdout
            pane_cmd = subprocess.run(
                ["tmux", "display-message", "-t", target, "-p", "#{pane_current_command}"],
                capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return None
        self._last_pane_snapshot = (out, pane_cmd)
        pane_state = _parse_pane_state(out, pane_cmd, self.agent_id)
        if AGENT_CLI == 'codex':
            self._observed_model = _runtime_model_from_pane(out)
            self._observed_effort = _runtime_effort_from_pane(out)
        else:
            self._observe_claude_model_effort(out)
        configured_model = _configured_model(self.agent_id)
        configured_effort = _expected_effort_name(_configured_effort(self.agent_id))
        pane_state.update({
            "runtime_model": self._observed_model,
            "runtime_effort": self._observed_effort,
            "configured_model": configured_model,
            "configured_effort": configured_effort,
            "model_mismatch": bool(
                (self._observed_model and configured_model and
                 self._observed_model != configured_model)
                or (self._observed_effort and configured_effort and
                    self._observed_effort.lower() != configured_effort.lower())),
        })
        return pane_state

    def _observe_claude_model_effort(self, recent_pane):
        """Relève uniquement les confirmations déjà rendues, sans écrire au TUI.

        `/model` et `/effort` sans argument sont des sélecteurs interactifs dans
        Claude Code. Les utiliser comme sondes laisse le menu ouvert et fige
        l'agent. Une information absente reste donc inconnue.
        """
        model_matches = re.findall(
            MARKERS['model_check_response_pattern'], recent_pane, re.MULTILINE)
        effort_matches = re.findall(
            MARKERS['effort_check_response_pattern'], recent_pane, re.MULTILINE)
        # Une pane peut contenir plusieurs changements successifs. La première
        # confirmation décrit alors un ancien état et produisait un faux
        # model_mismatch (donc un agent jaune) après un clic pourtant réussi.
        if model_matches:
            self._observed_model = _normalize_model_name(model_matches[-1])
        if effort_matches:
            self._observed_effort = effort_matches[-1].lower()

    def _heartbeat_loop(self):
        """Thread: heartbeat enrichi toutes les 10s — EF-003, CA-004.

        Publie 7 champs sur agent:{id}:heartbeat (CT-002, CT-009).
        Champs: agent_id, timestamp, status, memory_mb, cpu_percent,
                messages_processed, last_message_ts.
        B6: publie aussi pane_state (JSON) + pane_state_ts dans le hash agent.
        """
        self._set_listener_health("heartbeat", "up")
        try:
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
                    f"agent:{self.agent_id}:heartbeat",
                    data,
                    maxlen=STREAM_MAXLEN, approximate=True
                )
                self._last_heartbeat_ts = int(time.time())

                # Update last_seen in agent hash so dashboard doesn't show disconnected
                self.redis.hset(f"agent:{self.agent_id}", "last_seen", int(time.time()))

                # B6: publish pane-derived state so the dashboard skips tmux scans
                pane_state = self._derive_pane_state()
                if pane_state is not None:
                    snapshot = getattr(self, "_last_pane_snapshot", None)
                    if snapshot is not None:
                        # A10/EF-A3 : au plus UNE écriture TUI par battement.
                        # Un dialogue vu (répondu ou non) réserve le
                        # battement ; le flush A8 attendra le suivant — la
                        # collision auto-réponse + flush dans la même seconde
                        # a produit le « 0 » fantôme du 06/09.
                        dialog_seen = bool(
                            self._auto_respond_while_idle(*snapshot))
                    else:
                        dialog_seen = False
                    self._auth_blocked = bool(
                        pane_state.get("login_required"))
                    self.redis.hset(f"agent:{self.agent_id}", mapping={
                        "pane_state": json.dumps(pane_state),
                        "pane_state_ts": int(time.time()),
                        "auth_state": (
                            "blocked" if self._auth_blocked else "ready"),
                    })
                    # A8 : annexation avec échéance + composer orphelin. Les
                    # deux checks sont passifs et bornés ; une erreur ne doit
                    # jamais tuer le heartbeat.
                    try:
                        if not dialog_seen:
                            self._maybe_flush_parked(pane_state)
                    except Exception as exc:
                        self._log(f"ANNEX FLUSH check error: {exc}")
                    try:
                        pane_snapshot = getattr(
                            self, "_last_pane_snapshot", None)
                        self._check_composer_orphan(
                            pane_snapshot[0] if pane_snapshot else "",
                            pane_state)
                    except Exception as exc:
                        self._log(f"COMPOSER ORPHAN check error: {exc}")

                # Enregistrer dans métriques (R-INTEGRATE)
                if self.metrics:
                    self.metrics.record_heartbeat(self.agent_id, data)
                self._set_listener_health("heartbeat", "up")

            except redis.ConnectionError as e:
                self._set_listener_health("heartbeat", "degraded", e)
                self._log("Heartbeat: Redis connection lost")
            except Exception as e:
                self._set_listener_health("heartbeat", "degraded", e)
                self._record_metrics_error(e)
                self._log(f"Heartbeat error: {e}")

            time.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            import traceback
            self._set_listener_health("heartbeat", "down", e)
            self._log(f"FATAL: heartbeat crashed: {e}")
            self._log(traceback.format_exc())
        else:
            self._set_listener_health("heartbeat", "stopped")
        self._log("WARNING: heartbeat thread exiting")

    def _ensure_group(self):
        """A4: create the inbox consumer group (idempotent, ignore BUSYGROUP)."""
        try:
            self.redis.xgroup_create(self.inbox, self.group, id='$', mkstream=True)
        except redis.ResponseError as e:
            if 'BUSYGROUP' not in str(e):
                raise

    def _ack_inbox(self, msg_id):
        """A4: acknowledge an inbox message after successful handling."""
        try:
            self.redis.xack(self.inbox, self.group, msg_id)
        except Exception as e:
            self._log(f"XACK error for {msg_id}: {e}")
        # A5 : l'id n'est plus en vol — une eventuelle nouvelle livraison
        # (impossible apres XACK en temps normal) redeviendrait acceptable.
        with self._inflight_lock:
            self._inflight_ids.discard(msg_id)

    def _pending_streams(self):
        """Streams parqués à annexer au prochain vrai tour de CET agent.

        Tout stream qui a un écrivain doit avoir un lecteur. Le non-réveil
        reste la règle (anti-bruit v3.2.12), mais le contenu doit finir par
        atteindre son destinataire : sinon il est perdu alors que l'émetteur
        a lu `DELIVERED`. `reports` n'existe que pour un coordinateur de
        triangle ; `control`, `terminals` et `supervision` concernent TOUS
        les agents — y compris les IDs nus, pour lesquels le watchdog écrit
        déjà des TERMINAL_PENDING en promettant ce drainage.
        """
        streams = []
        if event_router.triangle_master(self.agent_id) == self.agent_id:
            streams.append((
                f"agent:{self.agent_id}:reports", "reports_cursor",
                "RAPPORTS DE SUPERVISION NOUVEAUX (information, ne pas "
                "les acquitter individuellement) :"))
        streams.extend((
            (f"agent:{self.agent_id}:control", "control_cursor",
             "CONTRÔLES NOUVEAUX (observation — aucun rapport en retour, "
             "au plus une relance corrélée par TERMINAL_PENDING) :"),
            (f"agent:{self.agent_id}:terminals", "terminals_cursor",
             "TERMINAUX REÇUS (déjà livrés — n'y réponds jamais par un "
             "terminal ; agis seulement si le contenu appelle un travail) :"),
            (f"agent:{self.agent_id}:supervision", "supervision_cursor",
             "MESSAGES DE SUPERVISION REÇUS (information, aucun "
             "acquittement) :"),
        ))
        return streams

    def _attach_pending_reports(self, task):
        """Ajoute un résumé borné au prochain vrai tour de l'agent.

        Couvre rapports, contrôles, terminaux reçus et supervision : un
        demandeur en WAITING constate le silence de sa cible, et un worker
        voit la question qui lui a été posée — sans réveil ni polling.
        """
        cursor_key = f"agent:{self.agent_id}"
        sections = []
        # Le message qui ouvre ce tour peut aussi exister dans un stream
        # parqué (rapport source, terminal canonique ou rejeu). L'annexer au
        # prompt le ferait apparaître deux ou trois fois dans le même tour.
        # Les identités v1 priment ; les aliases couvrent le hotfix antérieur.
        current_event_ids = {
            str(value) for value in (task.get("event_id", ""),)
            if value
        }
        # ``decision_id`` est transporté sur toutes les enveloppes v1 pour
        # l'audit, mais seules les décisions bloquantes partagent un slot de
        # déduplication report/wake/terminal. Passer ici par la même garde que
        # le routeur empêche un MESSAGE ordinaire de masquer un vrai terminal
        # annexé qui porte le même identifiant de tour.
        current_decision_ids = {
            str(value) for value in (event_router.decision_identity(task),)
            if value
        }
        current_report_ids = {
            str(value) for value in (
                task.get("source_report_id", ""),
                task.get("related_report_id", ""),
            ) if value
        }
        current_msg_id = str(task.get("msg_id", "") or "")
        current_source_turn = event_router.source_turn_id(task)
        current_status = event_router.decision_status(task)
        current_sender = str(task.get("from_agent", "") or "")
        # A8 : un même rapport existe dans DEUX streams (reports = l'original,
        # supervision = la copie wake classée par le routeur). Sans dédup
        # inter-streams, le Master lirait chaque rapport deux fois par annexe.
        seen_annex_ids = set()
        # A8 : références des entrées réellement annexées — le tour qui les
        # présente au modèle écrira leur accusé de lecture ma:bus:v1:read:*.
        annexed_refs = []
        for stream_name, cursor_field, header in self._pending_streams():
            try:
                cursor = self.redis.hget(cursor_key, cursor_field) or "-"
                minimum = f"({cursor}" if cursor != "-" else "-"
                entries = self.redis.xrange(
                    stream_name, min=minimum, max="+", count=20)
            except Exception as exc:
                self._log(f"REPORT BATCH READ ERROR: {exc}")
                continue
            if not entries:
                continue
            lines = []
            for report_id, fields in entries:
                entry_event_id = str(fields.get("event_id", "") or "")
                entry_decision_id = str(
                    event_router.decision_identity(fields) or "")
                entry_source_report_id = event_router.source_report_id(fields)
                entry_report_ids = {
                    str(value) for value in (
                        report_id,
                        fields.get("report_id", ""),
                        entry_source_report_id,
                    ) if value
                }
                same_current_entry = bool(
                    current_msg_id
                    and str(fields.get("original_msg_id", "") or "")
                    == current_msg_id)
                same_event = bool(
                    entry_event_id
                    and entry_event_id in current_event_ids)
                same_decision = bool(
                    entry_decision_id
                    and entry_decision_id in current_decision_ids)
                same_report = bool(
                    current_report_ids.intersection(entry_report_ids))
                same_legacy_decision = bool(
                    current_source_turn
                    and current_status
                    and event_router.source_turn_id(fields)
                    == current_source_turn
                    and event_router.decision_status(fields)
                    == current_status
                    and str(fields.get("from_agent", "") or "")
                    == current_sender)
                # Une décision bloquante peut être archivée après que son
                # autre représentation (wake ou terminal) a déjà ouvert le
                # tour modèle. Elle ne doit pas réapparaître comme bruit au
                # prochain vrai tour. Le registre inbound_decision est posé
                # avant la mise en queue et couvre les deux ordres d'arrivée.
                decision_already_consumed = False
                if entry_decision_id:
                    try:
                        reserved_by = self.redis.get(
                            f"inbound_decision:{self.agent_id}:"
                            f"{entry_decision_id}")
                        if isinstance(reserved_by, bytes):
                            reserved_by = reserved_by.decode(
                                errors="replace")
                        decision_already_consumed = bool(
                            isinstance(reserved_by, str) and reserved_by)
                    except Exception as exc:
                        # Fail-open : une panne de lecture du registre ne doit
                        # jamais faire disparaître une information non prouvée
                        # comme déjà traitée.
                        self._log(f"DECISION LEDGER READ ERROR: {exc}")
                if (same_current_entry or same_event or same_decision
                        or same_report or same_legacy_decision
                        or decision_already_consumed):
                    # Le curseur est malgré tout avancé après la boucle : une
                    # entrée filtrée ne doit pas revenir au tour suivant.
                    continue
                # A8 : dédup inter-streams au sein de cette annexe (le wake
                # d'un rapport partage report_id/decision_id avec l'original).
                # Identités LOGIQUES seulement : deux streams peuvent produire
                # le même id brut à la même milliseconde pour deux messages
                # sans rapport.
                entry_annex_ids = {
                    str(value) for value in (
                        entry_event_id,
                        entry_decision_id,
                        fields.get("report_id", ""),
                        entry_source_report_id,
                        fields.get("related_report_id", ""),
                    ) if value
                }
                if entry_annex_ids & seen_annex_ids:
                    continue
                seen_annex_ids |= entry_annex_ids
                # Un rapport porte summary/detail ; un terminal ou un message
                # de supervision porte son texte dans prompt. Sans ce repli,
                # le drainage annexerait des lignes vides.
                body = (fields.get("summary") or fields.get("detail")
                        or fields.get("prompt") or "")
                lines.append(
                    f"- {fields.get('from_agent', '?')} "
                    f"{fields.get('status', fields.get('event', 'STATUS'))}: "
                    f"{body[:300]}")
                annexed_refs.append({
                    "stream": stream_name,
                    "msg_id": str(report_id),
                    "event_id": entry_event_id,
                })
            self.redis.hset(cursor_key, cursor_field, entries[-1][0])
            if not lines:
                # Entrées sans corps lisible : avancer le curseur, mais ne
                # jamais annexer un en-tête sans contenu au prompt.
                continue
            sections.append(header + "\n" + "\n".join(lines))
        if not sections:
            return task
        enriched = dict(task)
        enriched["prompt"] = (
            task.get("prompt", "") + "\n\n" + "\n\n".join(sections))
        enriched["_annexed_refs"] = annexed_refs
        return enriched

    def _has_parked_pending(self):
        """A8 : au moins une entrée parquée au-delà des curseurs d'annexation."""
        cursor_key = f"agent:{self.agent_id}"
        for stream_name, cursor_field, _header in self._pending_streams():
            try:
                cursor = self.redis.hget(cursor_key, cursor_field) or "-"
                minimum = f"({cursor}" if cursor != "-" else "-"
                if self.redis.xrange(
                        stream_name, min=minimum, max="+", count=1):
                    return True
            except Exception as exc:
                self._log(f"PARKED PENDING CHECK ERROR: {exc}")
        return False

    def _maybe_flush_parked(self, pane_state=None):
        """A8 : annexation avec échéance — la lecture ne dépend plus d'un
        « prochain vrai tour » qui peut ne jamais arriver.

        Constat du 19/08 (triangle 334) : 11 messages classés supervision
        « stored; not injected into TUI » pendant 4 h chez un Master idle.
        L'émetteur avait lu DELIVERED, le destinataire n'a jamais rien vu.
        Quand l'agent est resté idle ANNEX_FLUSH_IDLE_S avec du contenu
        parqué, ce tour de synthèse borné présente tout le backlog en une
        seule injection. Il n'ouvre AUCUNE obligation (source hors 'redis' :
        ni terminal corrélé dû, ni MASTER_REPORT dû).
        """
        now = time.time()
        if self.state != State.IDLE:
            return False
        if not self.prompt_queue.empty():
            return False
        with self._inflight_lock:
            if self._inflight_ids:
                return False
        if now - self._last_turn_end_ts < ANNEX_FLUSH_IDLE_S:
            return False
        if now - self._last_flush_ts < ANNEX_FLUSH_MIN_INTERVAL_S:
            return False
        # Conservateur : sans lecture de pane fiable, ne pas injecter — le
        # prochain battement réessaiera.
        if not pane_state or pane_state.get("busy") \
                or pane_state.get("login_required") \
                or pane_state.get("waiting_approval"):
            return False
        if not self._has_parked_pending():
            return False
        task = {
            "prompt": (
                "SYNTHÈSE PÉRIODIQUE DES MESSAGES PARQUÉS — information, "
                "aucun acquittement ni rapport dû ; agis seulement si un "
                "contenu appelle réellement un travail."),
            "from_agent": "annex_flush",
            "msg_id": f"annex_flush_{int(now)}",
            "source": "annex_flush",
        }
        task = self._attach_pending_reports(task)
        self._last_flush_ts = now
        if not task.get("_annexed_refs"):
            # Le backlog entier était des doublons déjà consommés : curseurs
            # avancés, aucun tour modèle à ouvrir.
            return False
        self.prompt_queue.put(task)
        count = len(task["_annexed_refs"])
        self._log(
            f"ANNEX FLUSH queued — {count} parked message(s) "
            "will reach the TUI")
        self._log_event("annex_flush", f"count={count}")
        self._wal("annex_flush", None, count=count)
        return True

    def _publish_read_receipts(self, task):
        """A8 : accusés de lecture — un contenu présenté au modèle est READ.

        Couvre le message qui a ouvert le tour (event_id d'enveloppe v1) et
        chaque entrée parquée annexée à ce tour. DELIVERED reste un état de
        transport ; READ est l'état de consommation que le watchdog peut
        réconcilier avec une échéance.
        """
        refs = list(task.get("_annexed_refs") or [])
        own_event_id = str(task.get("event_id", "") or "")
        if own_event_id:
            refs.append({
                "stream": self.inbox,
                "msg_id": str(task.get("msg_id", "") or ""),
                "event_id": own_event_id,
            })
        if not refs:
            return
        now = int(time.time())
        turn_id = str(task.get("_turn_id", "") or "")
        try:
            pipe = self.redis.pipeline(transaction=False)
            for ref in refs:
                event_id = str(ref.get("event_id", "") or "")
                if event_id:
                    key = f"ma:bus:v1:read:{event_id}"
                else:
                    key = (
                        "ma:bus:v1:read:stream:"
                        f"{ref.get('stream', '')}:{ref.get('msg_id', '')}")
                pipe.hset(key, mapping={
                    "read_at": now,
                    "read_by": self.agent_id,
                    "turn_id": turn_id,
                    "stream": str(ref.get("stream", "") or ""),
                    "stream_id": str(ref.get("msg_id", "") or ""),
                })
                pipe.expire(key, READ_RECEIPT_TTL)
            pipe.hset(f"agent:{self.agent_id}", "last_read_at", now)
            pipe.execute()
        except Exception as exc:
            self._log(f"READ RECEIPT publish failed: {exc}")

    def _persist_turn_envelope(self, task):
        """A8 : conserver l'enveloppe du tour APRÈS sa fin (champs last_*).

        Le modèle continue souvent de travailler après que le bridge a conclu
        le tour (bashes en arrière-plan, notifications). Un report-master.sh
        émis à ce moment trouvait un hash vide (HDEL des current_*) et partait
        en TASK=unattributed / CORR=rescue-*. bus_protocol.resolve_context se
        replie désormais sur ces last_* tant qu'ils sont frais.
        """
        if not (task.get("correlation_id") or task.get("task_id")):
            # Un tour sans enveloppe métier (flush, CLI, auto-init) ne doit
            # jamais écraser le dernier contexte métier connu.
            return
        try:
            self.redis.hset(f"agent:{self.agent_id}", mapping={
                "last_turn_id": str(task.get("_turn_id", "") or ""),
                "last_task_id": str(task.get("task_id", "") or ""),
                "last_cycle": str(task.get("cycle", "") or ""),
                "last_correlation": str(task.get("correlation_id", "") or ""),
                "last_requester": str(task.get("from_agent", "") or ""),
                "last_owner": str(
                    task.get("owner", "") or self.agent_id),
                "last_turn_origin": str(task.get("source", "unknown")),
                "last_turn_ended_at": int(time.time()),
            })
        except Exception as exc:
            self._log(f"Turn envelope persist failed: {exc}")

    def _check_composer_orphan(self, pane_text, pane_state):
        """A8 : texte saisi dans le composer et jamais soumis (audit 27/07).

        Une instruction affichée dans un composer n'est pas un événement
        livré. Détection passive : même texte non vide, agent idle, stable
        au-delà de COMPOSER_ORPHAN_S → une alerte (jamais d'auto-submit).
        """
        state = self._composer_orphan
        if not pane_text or not pane_state or pane_state.get("busy") \
                or self.state != State.IDLE:
            state.update({"text": "", "since": 0.0, "alerted": False})
            return None
        text = ""
        for line in reversed(pane_text.splitlines()):
            stripped = line.lstrip()
            # Mêmes marqueurs de composer que _composer_contains_text.
            if stripped.startswith(("›", "❯")):
                text = stripped[1:].strip()
                break
        now = time.time()
        if not text:
            state.update({"text": "", "since": 0.0, "alerted": False})
            return None
        if text != state.get("text"):
            state.update({"text": text, "since": now, "alerted": False})
            return None
        if state.get("alerted") or now - state.get("since", now) \
                < COMPOSER_ORPHAN_S:
            return None
        state["alerted"] = True
        detail = (
            f"Agent {self.agent_id}: texte présent dans le composer sans "
            f"soumission depuis {int(now - state['since'])}s — instruction "
            "probablement perdue (utiliser send.sh, jamais de saisie tmux "
            "directe)")
        self._log(f"COMPOSER ORPHAN — {detail}")
        self._log_event("composer_orphan", text[:120])
        try:
            self.redis.xadd("monitoring:alerts", {
                "from": "bridge",
                "type": "alert:warning",
                "agent_id": self.agent_id,
                "message": detail,
                "timestamp": str(int(now)),
                "payload": json.dumps({"composer_excerpt": text[:200]}),
            }, maxlen=STREAM_MAXLEN, approximate=True)
        except Exception as exc:
            self._log(f"COMPOSER ORPHAN alert publish failed: {exc}")
        return detail

    def _handle_inbox_message(self, msg_id, data):
        """Handle one inbox stream message.

        Prompts carry ack_id and are XACK'd by _process_queue after the
        response is published; other types are XACK'd immediately.
        """
        if not data:
            # Entry trimmed from stream while pending — nothing to replay
            self._ack_inbox(msg_id)
            return

        # R-INTEGRATE: record inbound message
        if self.metrics:
            self.metrics.record_message(self.agent_id, "inbound")

        msg_type = data.get('type', 'prompt')
        event_class = event_router.classify(data)
        decision_id = event_router.decision_identity(data)
        if decision_id and not data.get("decision_id"):
            data = dict(data)
            data["decision_id"] = decision_id

        # Classer avant toute injection. Un rapport, un contrôle, un doublon ou
        # une enveloppe invalide ne doit jamais consommer un tour modèle.
        if event_class in ("supervision", "control", "quarantine"):
            stream = f"agent:{self.agent_id}:{event_class}"
            stored = dict(data)
            stored.update({
                "original_msg_id": str(msg_id),
                "classification": event_class,
                "classified_at": int(time.time()),
            })
            self.redis.xadd(
                stream, stored, maxlen=IO_STREAM_MAXLEN, approximate=True)
            self._wal(
                "event_suppressed", data.get("task_id"),
                suppressed_event=data.get("event", ""),
                classification=event_class,
                correlation_id=data.get("correlation_id", ""))
            self._log(
                f"<- {event_class.upper()} {data.get('event', '')} stored; "
                "not injected into TUI")
            self._ack_inbox(msg_id)
            return

        if event_class == "terminal":
            fingerprint = event_router.event_fingerprint(data)
            dedup_key = f"inbound_terminal:{self.agent_id}:{fingerprint}"
            event_reserved = self.redis.set(
                dedup_key, str(msg_id), nx=True, ex=604800)
            reserved_by = "" if event_reserved else self.redis.get(dedup_key)
            if isinstance(reserved_by, bytes):
                reserved_by = reserved_by.decode(errors="replace")
            if not event_reserved and str(reserved_by) != str(msg_id):
                self._wal(
                    "event_suppressed", data.get("task_id"),
                    suppressed_event=data.get("event", ""),
                    classification="duplicate",
                    correlation_id=data.get("correlation_id", ""))
                self._ack_inbox(msg_id)
                return
            stored = dict(data)
            stored.update({
                "original_msg_id": str(msg_id),
                "classification": "terminal",
                "classified_at": int(time.time()),
            })
            self.redis.xadd(
                f"agent:{self.agent_id}:terminals", stored,
                maxlen=IO_STREAM_MAXLEN, approximate=True)
            if not event_router.should_wake_for_terminal(self.agent_id, data):
                self._ack_inbox(msg_id)
                return
            # Un terminal neuf destiné au Master devient une décision
            # actionnable unique. Il ne crée aucune obligation de réponse vers
            # son émetteur et ne demande aucun MASTER_REPORT au Master.
            data = dict(data)
            if not data.get("status"):
                data["status"] = event_router.decision_status(data)
            data["event"] = "DECISION_REQUIRED"
            data["type"] = "prompt"
            data["prompt"] = (
                "NOUVEAU TERMINAL À APPLIQUER (ne pas l'acquitter par un "
                "terminal) : " + data.get("prompt", ""))
            msg_type = "prompt"

        # BLOCKED/INFO_REQUIRED peuvent parvenir deux fois : le réveil de
        # report-master.sh et le terminal canonique de done.sh. Le terminal
        # est archivé ci-dessus, mais une même décision n'ouvre qu'un tour
        # modèle, quel que soit l'ordre d'arrivée des deux canaux.
        if decision_id and event_class in ("terminal", "actionable"):
            decision_key = (
                f"inbound_decision:{self.agent_id}:{decision_id}")
            decision_reserved = self.redis.set(
                decision_key, str(msg_id), nx=True, ex=604800)
            reserved_by = (
                "" if decision_reserved else self.redis.get(decision_key))
            if isinstance(reserved_by, bytes):
                reserved_by = reserved_by.decode(errors="replace")
            if (not decision_reserved
                    and str(reserved_by) != str(msg_id)):
                self._wal(
                    "event_suppressed", data.get("task_id"),
                    suppressed_event=data.get("event", ""),
                    classification="decision_duplicate",
                    correlation_id=data.get("correlation_id", ""))
                self._log(
                    f"<- DECISION DUPLICATE {decision_id} stored/ignored; "
                    "not injected into TUI")
                self._ack_inbox(msg_id)
                return

        if msg_type == 'prompt' or 'prompt' in data:
            # A5 : dedup en vol — le drain pending (ou toute re-livraison)
            # peut representer un message pas encore XACK ; il est deja en
            # queue ou en cours d'execution, ne pas le re-queuer.
            with self._inflight_lock:
                if msg_id in self._inflight_ids:
                    self._log(f"DUPLICATE delivery {msg_id} ignored (in-flight, not re-queued)")
                    return
                self._inflight_ids.add(msg_id)
            raw_from = data.get('from_agent', 'unknown')
            safe_from = raw_from if re.fullmatch(
                rf'{AGENT_ID_PATTERN}|cli|manual|legacy|unknown|auto_init'
                rf'|compaction_reload|compaction_resume|verify|watchdog'
                rf'|response_{AGENT_ID_PATTERN}',
                str(raw_from)) else 'unknown'
            task = {
                'prompt': data.get('prompt', ''),
                'from_agent': safe_from,
                'msg_id': msg_id,
                'ack_id': msg_id,
                'correlation_id': data.get('correlation_id', ''),
                'cycle': data.get('cycle', ''),
                'event': data.get('event', ''),
                'expected_event': data.get('expected_event', ''),
                'requester': data.get('requester', ''),
                'owner': data.get('owner', ''),
                'schema_version': data.get('schema_version', ''),
                'event_id': data.get('event_id', ''),
                'decision_id': data.get('decision_id', ''),
                'source_turn_id': event_router.source_turn_id(data),
                'source_report_id': event_router.source_report_id(data),
                'related_report_id': data.get('related_report_id', ''),
                'turn_id': data.get('turn_id', ''),
                'status': data.get('status', ''),
                'classification': data.get('classification', ''),
                'payload_sha256': data.get('payload_sha256', ''),
                # V3 — absents = comportement v2 inchangé
                'verify_cmd': data.get('verify_cmd', ''),
                'task_id': data.get('task_id', ''),
                'project_dir': data.get('project_dir', ''),
                'deadline': data.get('deadline', ''),
                'source': 'redis'
            }
            task = self._attach_pending_reports(task)
            try:
                created = obligations.create(BASE_DIR, self.agent_id, task, msg_id)
                if created:
                    self._log(f"Obligation ouverte: {created}")
            except Exception as exc:
                # Ne pas exécuter un DISPATCH dont l'obligation durable n'a pas
                # pu être créée : sans elle, un silence redeviendrait invisible.
                with self._inflight_lock:
                    self._inflight_ids.discard(msg_id)
                self._log(f"Obligation create failed for {msg_id}: {exc}")
                return
            self.prompt_queue.put(task)
            self._log(f"<- Queued from {safe_from}: {data.get('prompt', '')[:50]}...")
        elif msg_type == 'reload_prompt':
            self._log("Received reload_prompt — reloading agent personality")
            self._reload_prompt()
            self._ack_inbox(msg_id)
        elif msg_type == 'response':
            from_id = data.get('from_agent', '?')
            response_text = data.get('response', '')
            raw_chunk = data.get('chunk', '')
            chunk_info = raw_chunk if re.fullmatch(r'[\w\-/. ]{0,30}', str(raw_chunk)) else ''
            is_complete = data.get('complete', 'true')

            self._log(f"<- Response from {from_id} ({len(response_text)} chars){' ['+chunk_info+']' if chunk_info else ''}")

            # Une transcription est un artefact de diagnostic, pas un
            # evenement metier. L'outbox de l'emetteur la conserve deja ; la
            # reinjecter dans le TUI du destinataire pollue son contexte avec
            # des marqueurs d'UI. Les signaux actionnables passent par un
            # message prompt explicite (send.sh / done.sh).
            self._log(
                f"Response transcript from {from_id} stored in sender outbox; "
                "not injected into TUI")
            self._ack_inbox(msg_id)
        else:
            self._log(f"<- Unknown message type '{msg_type}' from {data.get('from_agent', '?')} — acked")
            self._ack_inbox(msg_id)

    def _listen_redis(self):
        """Thread: listen to Redis inbox via consumer group (A4: XREADGROUP + XACK).

        On startup, unacked messages from a previous run (crash) are drained
        first (id '0'), then new messages are consumed (id '>').
        """
        group_ready = False
        pending_drained = False
        # A6 : ne rien livrer avant que run() ait mis l'auto-init en queue —
        # sinon les pending recovery doublent le « deviens agent ». Timeout de
        # sécurité : on ne reste jamais bloqué si run() n'a rien à charger.
        # getattr : les tests instancient sans __init__ (object.__new__).
        _gate = getattr(self, "_auto_init_queued", None)
        if _gate is not None and not _gate.wait(timeout=30):
            self._log("WARNING: auto-init non signalé après 30s — drain pending quand même")
        self._set_listener_health("redis_listener", "up")
        try:
         while self.running:
            try:
                if not group_ready:
                    self._ensure_group()
                    group_ready = True

                # Redis reste l'unique tampon : un seul prompt Redis peut etre
                # reclame a la fois. Tant qu'il n'est pas publie puis XACK, le
                # listener ne precharge pas les messages suivants en memoire.
                with self._inflight_lock:
                    has_inflight = bool(self._inflight_ids)
                if has_inflight:
                    time.sleep(0.2)
                    continue

                if not pending_drained:
                    # A5 (fix re-injection 11/07) : curseur AVANCANT. L'ancien
                    # code relisait la PEL depuis '0' a chaque tour — un prompt
                    # reste pending jusqu'a son XACK (apres traitement), donc
                    # la boucle re-queuait LE MEME message en continu (19393
                    # "Recovering" constates, 130 injections du meme dispatch).
                    # Avec le curseur, chaque entree pending est livree UNE
                    # fois par demarrage ; le rejeu au restart est preserve.
                    cursor = '0'
                    while self.running:
                        result = self.redis.xreadgroup(
                            self.group, self.consumer, {self.inbox: cursor}, count=1)
                        messages = result[0][1] if result else []
                        if not messages:
                            break
                        self._log(f"Recovering {len(messages)} pending message(s) from previous run")
                        for msg_id, data in messages:
                            self._handle_inbox_message(msg_id, data)
                            cursor = msg_id
                        with self._inflight_lock:
                            if self._inflight_ids:
                                break
                    with self._inflight_lock:
                        if self._inflight_ids:
                            continue
                    pending_drained = True

                result = self.redis.xreadgroup(
                    self.group, self.consumer, {self.inbox: '>'}, block=2000, count=1)
                if result:
                    stream, messages = result[0]
                    for msg_id, data in messages:
                        self._handle_inbox_message(msg_id, data)
                self._set_listener_health("redis_listener", "up")
            except redis.ConnectionError as e:
                group_ready = False
                self._set_listener_health("redis_listener", "degraded", e)
                self._log("Redis connection lost, reconnecting...")
                time.sleep(2)
            except Exception as e:
                # ResponseError includes MISCONF/AOF failures. Keep the
                # listener supervised and retry after resetting group state.
                group_ready = False
                self._set_listener_health("redis_listener", "degraded", e)
                self._log(f"Redis error: {e}")
                self._record_metrics_error(e)
                time.sleep(1)
        except Exception as e:
            import traceback
            self._set_listener_health("redis_listener", "down", e)
            self._log(f"FATAL: redis_listener crashed: {e}")
            self._log(traceback.format_exc())
        else:
            self._set_listener_health("redis_listener", "stopped")
        self._log("WARNING: redis_listener thread exiting")

    def _listen_legacy(self):
        """Thread: listen to legacy Redis inbox (List format: A:inject:{id})

        Supports FROM:xxx| prefix to identify sender:
          RPUSH inject:NNN "FROM:NNN|do something"

        A4: legacy Lists stay best-effort (BLPOP pops destructively, no ack) —
        a crash between BLPOP and processing loses the message. Use Streams.
        """
        self._set_listener_health("legacy_listener", "up")
        try:
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
                            raw_from = parts[0][5:]
                            if re.fullmatch(rf'{AGENT_ID_PATTERN}|cli|manual', str(raw_from)):
                                from_agent = raw_from
                            prompt = parts[1]

                    self.prompt_queue.put({
                        'prompt': prompt,
                        'from_agent': from_agent,
                        'msg_id': f"legacy-{int(time.time())}",
                        'source': 'legacy'
                    })
                    self._log(f"<- Queued from {from_agent}: {prompt[:50]}...")
                self._set_listener_health("legacy_listener", "up")
            except redis.ConnectionError as e:
                self._set_listener_health("legacy_listener", "degraded", e)
                time.sleep(2)
            except Exception as e:
                self._set_listener_health("legacy_listener", "degraded", e)
                self._log(f"Legacy Redis error: {e}")
                self._record_metrics_error(e)
                time.sleep(1)
        except Exception as e:
            import traceback
            self._set_listener_health("legacy_listener", "down", e)
            self._log(f"FATAL: legacy_listener crashed: {e}")
            self._log(traceback.format_exc())
        else:
            self._set_listener_health("legacy_listener", "stopped")
        self._log("WARNING: legacy_listener thread exiting")

    def _requires_correlated_event(self, task):
        """Seul un vrai travail ouvre une obligation de réponse.

        Arbitrage 2026-07-28 : MESSAGE et INFO_REQUIRED restent gardés tant
        que send.sh émet MESSAGE par défaut entre agents ; seul l'événement
        vide (enveloppe legacy fabriquée hors send.sh) sort de la garde —
        c'était la classe majeure de faux positifs de fin de tour.
        """
        requester = str(task.get("from_agent", ""))
        return (
            task.get("source") == "redis"
            and str(task.get("event", "") or "").upper()
            in ("MESSAGE", "DISPATCH", "INFO_REQUIRED")
            and bool(task.get("correlation_id"))
            and bool(task.get("task_id"))
            and bool(task.get("cycle"))
            and requester not in (
                "", "cli", "manual", "legacy", "unknown", "auto_init",
                "compaction_reload", "compaction_resume", "verify", "watchdog")
            and is_valid_agent_id(requester)
        )

    def _requires_master_report(self, task):
        """Un rapport est dû après un travail, jamais après du contrôle."""
        if not self._triangle_master_id():
            return False
        event = str(task.get("event", "") or "").upper()
        return (
            task.get("source") == "redis"
            and event in ("MESSAGE", "DISPATCH", "INFO_REQUIRED")
            and str(task.get("from_agent", "")) != "watchdog"
        )

    def _api_retry_task(self, task, retry_count):
        """C4 : copie complète bornée d'un tour pour un retry API.

        Ne reconstruit PAS le dict à la main : cela perdait event,
        expected_event, requester, owner et l'identité de tour. Un tour non
        gardé (event hors ensemble corrélé) redevenait gardé après retry
        (event perdu = "") et rouvrait le faux positif de fin de tour. On
        préserve toute l'enveloppe et on ne surcharge que les compteurs.
        """
        retry_task = dict(task)
        retry_task['_retry_count'] = retry_count + 1
        retry_task['_verify_retry'] = task.get('_verify_retry', 0)
        retry_task.setdefault('source', 'retry')
        return retry_task

    def _has_correlated_business_event(self, task):
        """Check explicit send.sh/done.sh delivery for this correlation."""
        correlation_id = str(task.get("correlation_id", ""))
        requester = str(task.get("from_agent", ""))
        if not correlation_id or not requester:
            return False
        try:
            started_at = int(task.get("_turn_started_at", 0) or 0)
            for _, fields in self.redis.xrevrange("completion", count=200):
                if (
                    fields.get("correlation_id") == correlation_id
                    and fields.get("from") == self.agent_id
                    and int(fields.get("timestamp", 0) or 0) >= started_at
                ):
                    return True
            for _, fields in self.redis.xrevrange(
                    f"agent:{requester}:inbox", count=200):
                if (
                    fields.get("correlation_id") == correlation_id
                    and fields.get("from_agent") == self.agent_id
                    and fields.get("event") not in ("", "DISPATCH")
                    and str(fields.get("event", "") or "").upper()
                    != "DECISION_REQUIRED"
                    and str(fields.get("classification", "") or "").lower()
                    != "supervision_blocking"
                    and int(fields.get("timestamp", 0) or 0) >= started_at
                ):
                    return True
        except Exception as exc:
            # Redis indisponible : ne pas conclure à tort que le protocole est
            # respecté. La relance restera pending et sera rejouée.
            self._log(f"PROTOCOL EVENT CHECK ERROR: {exc}")
        return False

    def _triangle_master_id(self):
        """Return NNN-1ZZ for NNN-YZZ, excluding the Master itself."""
        if not is_valid_agent_id(self.agent_id) or "-" not in self.agent_id:
            return ""
        triangle, member = self.agent_id.split("-", 1)
        if len(member) != 3:
            return ""
        master = f"{triangle}-1{member[1:]}"
        return "" if master == self.agent_id else master

    def _has_master_report(self, task):
        master = self._triangle_master_id()
        turn_id = str(task.get("_turn_id", ""))
        if not master or not turn_id:
            return True
        try:
            state = self.redis.hgetall(f"agent:{self.agent_id}") or {}
            if not isinstance(state, dict):
                state = {}
            recorded_report_id = str(
                state.get("last_master_report_id", "") or "")
            recorded_source_turn = str(
                state.get("last_master_report_source_turn_id", "")
                or state.get("last_master_report_turn_id", "")
                or "")
            # État v1 écrit atomiquement avec le rapport.
            if (recorded_report_id
                    and recorded_source_turn == turn_id):
                return True
            for stream_id, fields in self.redis.xrevrange(
                    f"agent:{master}:reports", count=200):
                if (fields.get("from_agent") != self.agent_id
                        or fields.get("event") != "MASTER_REPORT"):
                    continue
                source_turn = event_router.source_turn_id(fields)
                report_id = str(
                    fields.get("report_id", "") or stream_id or "")
                if source_turn == turn_id:
                    # Si l'état local pointe un report précis, reconnaître
                    # son ID Redis ou son report_id v1. Sans pointeur (legacy),
                    # le tour source porté par le stream suffit.
                    if (not recorded_report_id
                            or recorded_report_id in {
                                report_id, str(stream_id), turn_id}):
                        return True
                # Compatibilité v3.2.12-v3.2.18.
                if fields.get("correlation_id") == f"turn-{turn_id}":
                    return True
        except Exception as exc:
            self._log(f"MASTER REPORT CHECK ERROR: {exc}")
        return False

    def _publish_master_report_error(self, task):
        master = self._triangle_master_id()
        turn_id = str(task.get("_turn_id", ""))
        if not master or not turn_id:
            return False
        key = f"master_report_error:{self.agent_id}:{turn_id}"
        try:
            if not self.redis.set(key, int(time.time()), nx=True, ex=604800):
                return True
            details = (
                f"Agent {self.agent_id}: fin de tour sans MASTER_REPORT "
                f"après une relance bornée; turn={turn_id}")
            self.redis.xadd(
                f"agent:{master}:control", {
                    "from_agent": "watchdog",
                    "event": "PROTOCOL_ERROR",
                    "classification": "control",
                    "detail": details,
                    "owner": self.agent_id,
                    "turn_id": turn_id,
                    "timestamp": int(time.time()),
                }, maxlen=IO_STREAM_MAXLEN, approximate=True)
            self._wal(
                "master_report_error", task.get("task_id"),
                turn_id=turn_id, master=master)
            return True
        except Exception as exc:
            self._log(f"MASTER REPORT ERROR publish failed: {exc}")
            return False

    def _publish_protocol_error(self, task):
        """Publish a correlated failure without fabricating DONE or SCORE."""
        requester = str(task.get("from_agent", ""))
        correlation_id = str(task.get("correlation_id", ""))
        task_id = str(task.get("task_id", ""))
        cycle = str(task.get("cycle", ""))
        if not is_valid_agent_id(requester) or not correlation_id:
            return False
        dedup_key = f"protocol_error:{self.agent_id}:{correlation_id}"
        try:
            reserved = self.redis.set(
                dedup_key, int(time.time()), nx=True, ex=604800)
            if not reserved:
                return True
            details = (
                f"Agent {self.agent_id}: fin de tour sans événement métier "
                "après une relance bornée")
            common = {
                "from": "watchdog",
                "to": requester,
                "event": "PROTOCOL_ERROR",
                "signal": f"PROTOCOL_ERROR {details}",
                "origin": "bridge",
                "correlation_id": correlation_id,
                "task_id": task_id,
                "cycle": cycle,
                "requester": requester,
                "owner": self.agent_id,
                "timestamp": int(time.time()),
            }
            self.redis.xadd(
                "completion", common, maxlen=STREAM_MAXLEN, approximate=True)
            inbox_event = {
                "from_agent": "watchdog",
                "event": "PROTOCOL_ERROR",
                "classification": "control",
                "detail": details,
                "correlation_id": correlation_id,
                "task_id": task_id,
                "cycle": cycle,
                "requester": requester,
                "owner": self.agent_id,
                "timestamp": int(time.time()),
            }
            self.redis.xadd(
                f"agent:{requester}:control", inbox_event,
                maxlen=IO_STREAM_MAXLEN, approximate=True)
            self._log(
                f"PROTOCOL_ERROR delivered to {requester}; corr={correlation_id}")
            self._wal(
                "protocol_error", task_id, correlation_id=correlation_id,
                requester=requester)
            return True
        except Exception as exc:
            self._log(f"PROTOCOL_ERROR publish failed: {exc}")
            return False

    def _publish_terminal_pending(self, task, missing_correlated,
                                  missing_master_report):
        """Expose a missing end-of-turn signal without inventing a failure.

        A model turn returning to a stable composer is not proof that the
        business task failed. This status is local/control-plane only: it
        creates no agent-to-agent acknowledgement loop and no completion.
        """
        correlation_id = str(task.get("correlation_id", ""))
        task_id = str(task.get("task_id", ""))
        details = {
            "from_agent": "watchdog",
            "event": "TERMINAL_PENDING",
            "classification": "control",
            "correlation_id": correlation_id,
            "task_id": task_id,
            "cycle": str(task.get("cycle", "")),
            "requester": str(task.get("from_agent", "")),
            "owner": self.agent_id,
            "missing_correlated": "1" if missing_correlated else "0",
            "missing_master_report": "1" if missing_master_report else "0",
            "timestamp": int(time.time()),
        }
        try:
            self.redis.xadd(
                f"agent:{self.agent_id}:control", details,
                maxlen=IO_STREAM_MAXLEN, approximate=True)
            self.redis.hset(
                f"agent:{self.agent_id}", mapping={
                    "protocol_state": "terminal_pending",
                    "protocol_correlation": correlation_id,
                    "protocol_task": task_id,
                    "protocol_state_ts": int(time.time()),
                })
            self._wal(
                "terminal_pending", task_id,
                correlation_id=correlation_id,
                requester=task.get("from_agent", ""),
                missing_correlated=missing_correlated,
                missing_master_report=missing_master_report)
            self._log(
                "TERMINAL_PENDING — business completion not observed; "
                f"corr={correlation_id}")
            return True
        except Exception as exc:
            self._log(f"TERMINAL_PENDING publish failed: {exc}")
            return False

    def _process_queue(self):
        """Thread: process prompt queue"""
        try:
         while self.running:
            try:
                task = self.prompt_queue.get(timeout=1)
            except Empty:
                continue

            # A5 : l'etat de verite est Redis — un message XDEL/trim de
            # l'inbox pendant qu'il attendait en queue memoire ne doit PAS
            # etre injecte (l'operateur l'a annule). Coherent avec le drain
            # (entry trimmed while pending -> ack, nothing to replay).
            if task.get('ack_id') and task.get('source') == 'redis':
                try:
                    still_there = self.redis.xrange(
                        self.inbox, task['ack_id'], task['ack_id'])
                except Exception:
                    still_there = [True]  # Redis KO : ne pas perdre la tache
                if not still_there:
                    self._log(f"Message {task['ack_id']} deleted from inbox (XDEL) — dropping, not injecting")
                    self._ack_inbox(task['ack_id'])
                    continue

            with self.state_lock:
                tui_reserved = self.state == State.BUSY
                if not tui_reserved:
                    self.state = State.BUSY
                    self.current_task = task
            if tui_reserved:
                self.prompt_queue.put(task)
                time.sleep(0.1)
                continue

            self._set_redis_status()
            src = f"[{task.get('from_agent', 'local')}]"
            self._log(f"-> Executing {src}: {task['prompt'][:80]}...")
            task.setdefault("_turn_id", str(uuid.uuid4()))
            task.setdefault("_turn_started_at", int(time.time()))
            delivery_obligation = self._requires_correlated_event(task)
            master_report_obligation = self._requires_master_report(task)
            event_name = str(task.get("event", "") or "").upper()
            source_name = str(task.get("source", "unknown") or "unknown")
            if source_name == "auto_init":
                turn_kind = "AUTO_INIT"
            elif event_name in (
                    "CONTROL", "PROTOCOL_ERROR", "STATUS_REQUIRED",
                    "MASTER_REPORT", "DECISION_REQUIRED"):
                turn_kind = "CONTROL"
            elif str(task.get("from_agent", "")) in ("cli", "manual"):
                turn_kind = "CLI"
            elif source_name == "redis":
                turn_kind = "TASK"
            else:
                turn_kind = source_name.upper()
            try:
                self.redis.hset(f"agent:{self.agent_id}", mapping={
                    "current_correlation": task.get("correlation_id", ""),
                    "current_task_id": task.get("task_id", ""),
                    "current_cycle": task.get("cycle", ""),
                    "current_requester": task.get("from_agent", ""),
                    "current_owner": task.get("owner", "") or self.agent_id,
                    "current_task_started_at": task["_turn_started_at"],
                    "current_turn_id": task["_turn_id"],
                    "current_turn_origin": task.get("source", "unknown"),
                    "current_turn_kind": turn_kind,
                    "bus_schema_version": BUS_SCHEMA_VERSION,
                    "current_delivery_obligation": int(delivery_obligation),
                    "current_master_report_obligation": int(
                        master_report_obligation),
                })
            except Exception:
                pass

            # R-INTEGRATE: record task start
            if self.metrics:
                self.metrics.record_task_start(self.agent_id, task_id=task.get('msg_id'))

            self._wal("task_assigned", task.get('task_id'),
                      source=task.get('source', ''),
                      from_agent=task.get('from_agent', ''))

            # === V3/C2 : budget wall-time ===
            # deadline (epoch) portée par la tâche = borne du temps total,
            # retries de verify compris. Absente : comportement v2 inchangé.
            deadline_expired = False
            try:
                deadline_expired = (bool(task.get('deadline'))
                                    and time.time() > float(task['deadline']))
            except (TypeError, ValueError):
                deadline_expired = False

            if deadline_expired:
                self._log(f"DEADLINE dépassée: task={task.get('task_id')}")
                self._log_event("verify_escalation",
                                f"task={task.get('task_id')} motif=deadline")
                self._wal("verify_escalation", task.get('task_id'),
                          motif="deadline")
                response = (f"[VERIFY_FAILED] BLOCKED|task={task.get('task_id')}"
                            f"|raison=deadline")
            else:
                # Run prompt
                try:
                    delivered_prompt = task['prompt']
                    if task.get('source') == 'redis':
                        delivered_prompt = (
                            "[ENVELOPPE BRIDGE — recopier ces valeurs dans toute réponse métier]\n"
                            f"FROM={task.get('from_agent', 'unknown')}\n"
                            f"TASK={task.get('task_id', '') or 'unknown'}\n"
                            f"CYCLE={task.get('cycle', '') or 'unknown'}\n"
                            f"CORR={task.get('correlation_id', '') or 'legacy'}\n"
                            "[FIN ENVELOPPE]\n\n"
                            f"{task['prompt']}"
                        )
                    tui_lock = getattr(self, '_tui_lock', None)
                    if tui_lock is None:
                        tui_lock = Lock()
                        self._tui_lock = tui_lock
                    with tui_lock:
                        response = self._run_claude(delivered_prompt)
                except Exception as e:
                    self._log(f"ERROR running Claude: {e}")
                    if self.metrics:
                        self.metrics.record_error(self.agent_id, type(e).__name__, str(e))
                    response = f"[ERROR] {e}"

            if response == "__BRIDGE_STOPPED__":
                self._log("Bridge stopped while task active — leaving Redis entry pending")
                break

            # API error detection — retry with backoff (max 2 retries)
            # A1: motifs externalisés dans markers.yaml (API_ERROR_PATTERNS)
            retry_count = task.get('_retry_count', 0)
            is_api_error = _matches_api_error(response)

            if is_api_error and retry_count < 2:
                self._log(f"API ERROR detected (retry {retry_count+1}/2), re-queuing prompt")
                self._log_event("api_error_retry", f"retry={retry_count+1}")
                self._wal("api_error_retry", task.get('task_id'),
                          retry=retry_count + 1)
                try:
                    self.redis.hset(
                        f"agent:{self.agent_id}",
                        mapping={
                            "status": "retrying",
                            "last_error": "api_error",
                            "last_error_at": int(time.time()),
                            "current_correlation":
                                task.get("correlation_id", ""),
                        })
                except Exception:
                    pass
                self.prompt_queue.put(
                    self._api_retry_task(task, retry_count))
                with self.state_lock:
                    self.current_task = None
                    self.state = State.IDLE
                self._set_redis_status()
                time.sleep(RETRY_BACKOFF_SECS)
                continue

            # Compaction detected — re-queue with identity + context reminder
            if response == self._COMPACTION_SENTINEL:
                self._log(f"COMPACTION: re-queuing with identity + context reminder")
                try:
                    self.redis.hset(f"agent:{self.agent_id}", "status", "context_compacted")
                except Exception:
                    pass

                # Drain any stale compaction_resume messages from previous attempts
                # (prevents message_2 from old round running before message_1 of new round)
                kept = []
                drained = 0
                while not self.prompt_queue.empty():
                    try:
                        item = self.prompt_queue.get_nowait()
                        if item.get('from_agent') == 'compaction_resume':
                            drained += 1
                        else:
                            kept.append(item)
                    except Empty:
                        break
                for item in kept:
                    self.prompt_queue.put(item)
                if drained:
                    self._log(f"COMPACTION: drained {drained} stale resume messages from queue")

                # Build resume: identity + history + current task (2 sequential messages)
                prompt_path = self._find_prompt_file()
                # Use original prompt unless this was already a resume attempt
                if task.get('from_agent') == 'compaction_resume':
                    original_prompt = task.get('_original_prompt', task['prompt'])
                else:
                    original_prompt = task['prompt']

                # Read last timestamped entry from .history file
                last_history = ""
                try:
                    if prompt_path:
                        hf = Path(prompt_path).parent / f"{self.agent_id}.history"
                        if hf.exists():
                            for line in reversed(hf.read_text().strip().split('\n')):
                                if line and line[:4].isdigit() and ' | ' in line[:25]:
                                    last_history = line
                                    break
                except Exception:
                    pass

                # Message 1: reload identity
                self.prompt_queue.put({
                    'prompt': f"deviens agent {prompt_path}",
                    'from_agent': 'compaction_resume',
                    'msg_id': f"resume1_{int(time.time())}",
                    '_original_prompt': original_prompt,
                })

                # Message 2: context reminder (queued, will run after msg 1)
                parts = []
                if last_history:
                    parts.append(f"Dernière ligne de ton historique : \"{last_history}\"")
                parts.append(f"Tu étais en train de travailler sur ce prompt : \"{original_prompt}\"")
                parts.append("Continue.")
                self.prompt_queue.put({
                    'prompt': "\n".join(parts),
                    'from_agent': 'compaction_resume',
                    'msg_id': f"resume2_{int(time.time())}",
                    'ack_id': task.get('ack_id'),
                    'correlation_id': task.get('correlation_id', ''),
                    'cycle': task.get('cycle', ''),
                    # V3 : la reprise post-compaction conserve le gate verify
                    'verify_cmd': task.get('verify_cmd', ''),
                    'project_dir': task.get('project_dir', ''),
                    'task_id': task.get('task_id', ''),
                    'deadline': task.get('deadline', ''),
                    '_verify_retry': task.get('_verify_retry', 0),
                })

                with self.state_lock:
                    self.current_task = None
                    self.state = State.IDLE
                self._set_redis_status()
                continue

            # === V3/C1 : verify gate ===
            # DONE candidat = fin de réponse d'une tâche portant verify_cmd.
            # Sans verify_cmd : flux v2 inchangé (rétrocompatibilité).
            if task.get('verify_cmd') and not deadline_expired:
                verify_started = time.monotonic()
                verify_cwd = PROJECT_DIR
                requested_cwd = task.get('project_dir', '')
                if requested_cwd:
                    requested_path = Path(requested_cwd).resolve()
                    sandbox_root = (BASE_DIR / 'bench' / 'sandbox').resolve()
                    try:
                        requested_path.relative_to(sandbox_root)
                        verify_cwd = str(requested_path)
                    except ValueError:
                        self._log(f"Ignored project_dir outside bench sandbox: {requested_path}")
                green, hacked, rapport = verifier.run(
                    task, self.redis, self.agent_id, verify_cwd)
                verify_wall_s = round(time.monotonic() - verify_started, 6)
                usage_fields = {
                    key: task[key] for key in
                    ('tokens_in', 'tokens_out', 'tokens_cached', 'usd_est')
                    if task.get(key) not in (None, '')
                }
                if green:
                    response += "\n[VERIFY_GREEN]"
                    self._log_event("verify_green", f"task={task.get('task_id')}")
                    self._wal("verify_green", task.get('task_id'),
                              verify_wall_s=verify_wall_s, **usage_fields)
                else:
                    n = int(task.get('_verify_retry', 0))
                    if not hacked and n < VERIFY_MAX_RETRIES:
                        self._log_event("verify_red",
                                        f"task={task.get('task_id')} retry={n+1}")
                        self._wal("verify_red", task.get('task_id'), retry=n + 1,
                                  verify_wall_s=verify_wall_s, **usage_fields)
                        self.prompt_queue.put({
                            'prompt': (f"FROM:verify|FAIL (tentative {n+1}/"
                                       f"{VERIFY_MAX_RETRIES})\n{rapport}\n"
                                       "Lis l'erreur, répare, le verify sera relancé."),
                            'from_agent': 'verify',
                            'msg_id': task.get('msg_id', ''),
                            'ack_id': task.get('ack_id'),
                            'correlation_id': task.get('correlation_id', ''),
                            'cycle': task.get('cycle', ''),
                            'verify_cmd': task['verify_cmd'],
                            'project_dir': task.get('project_dir', ''),
                            'task_id': task.get('task_id', ''),
                            'deadline': task.get('deadline', ''),
                            '_verify_retry': n + 1,
                            'source': 'verify_retry'
                        })
                        self._wal("verify_retry", task.get('task_id'), retry=n + 1)
                        with self.state_lock:
                            self.current_task = None
                            self.state = State.IDLE
                        self._set_redis_status()
                        continue  # l'ack_id reste porté par le retry (A4)
                    # Budget épuisé ou hacking : échec explicite, escalade
                    motif = "hacking" if hacked else "budget_retries"
                    self._log_event("verify_escalation",
                                    f"task={task.get('task_id')} motif={motif}")
                    self._wal("verify_escalation", task.get('task_id'),
                              motif=motif, verify_wall_s=verify_wall_s,
                              **usage_fields)
                    response = (f"[VERIFY_FAILED] BLOCKED|task={task.get('task_id')}"
                                f"|raison={motif}\n{rapport}")

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
            # F2: echo correlation_id so readers match response to request
            if task.get('correlation_id'):
                msg_data['correlation_id'] = task['correlation_id']
            self.redis.xadd(self.outbox, msg_data, maxlen=IO_STREAM_MAXLEN, approximate=True)
            self._wal(
                "response_published",
                task.get('task_id'),
                correlation_id=task.get('correlation_id', ''),
                cycle=task.get('cycle', ''),
                from_agent=task.get('from_agent', ''),
                chars=len(response),
            )

            # Une transcription dans l'outbox n'est pas une livraison métier.
            # Pour toute enveloppe inter-agent, exiger un événement explicite
            # send.sh/done.sh. L'absence de terminal à la fin du rendu TUI est
            # observable mais ne prouve ni un timeout ni un échec métier.
            missing_correlated = (
                self._requires_correlated_event(task)
                and not self._has_correlated_business_event(task))
            missing_master_report = (
                self._requires_master_report(task)
                and not self._has_master_report(task))
            if missing_correlated or missing_master_report:
                self._publish_terminal_pending(
                    task, missing_correlated, missing_master_report)
            else:
                try:
                    self.redis.hset(
                        f"agent:{self.agent_id}", mapping={
                            "protocol_state": "complete",
                            "protocol_correlation": task.get(
                                "correlation_id", ""),
                            "protocol_task": task.get("task_id", ""),
                            "protocol_state_ts": int(time.time()),
                        })
                except Exception as exc:
                    self._log(f"Protocol state publish failed: {exc}")

            # A4: ack only after the response is published to the outbox
            if task.get('ack_id'):
                self._ack_inbox(task['ack_id'])

            # A8 : le contenu de ce tour (message + annexes parquées) a été
            # présenté au modèle et le tour est terminé → accusés de lecture.
            self._publish_read_receipts(task)

            # R-INTEGRATE: record outbound message
            if self.metrics:
                self.metrics.record_message(self.agent_id, "outbound")

            # EF-003: update message counters
            self._messages_processed += 1
            self._last_message_ts = int(time.time())

            # A7: no DONE/SCORE scraping of model output — completion signals
            # go through the explicit channel only (scripts/done.sh → Redis)

            # La reponse canonique reste dans l'outbox, correlee si demande.
            # Elle n'est jamais recopied automatiquement dans l'inbox d'un
            # autre agent. Les evenements metier courts sont emis explicitement
            # avec send.sh/done.sh.

            self._log(f"Response sent ({len(response)} chars)")
            self.tasks_completed += 1
            self.messages_since_reload += 1

            with self.state_lock:
                self.current_task = None
                self.state = State.IDLE
            self._last_turn_end_ts = time.time()

            # A8 : conserver l'enveloppe métier du tour (last_*) AVANT
            # d'effacer les current_* — le modèle rapporte souvent après la
            # fin de tour vue par le bridge.
            self._persist_turn_envelope(task)
            try:
                self.redis.hdel(
                    f"agent:{self.agent_id}",
                    "current_correlation", "current_task_id", "current_cycle",
                    "current_requester", "current_owner",
                    "current_task_started_at",
                    "current_turn_id", "current_turn_origin",
                    "current_turn_kind",
                    "current_delivery_obligation",
                    "current_master_report_obligation")
            except Exception:
                pass
            self._set_redis_status()

            # Check for background bashes after response
            try:
                pane = self._capture_pane(10)
                if "bashes" in pane or "bash" in pane.split('\n')[-1]:
                    self.redis.hset(f"agent:{self.agent_id}", "status", "has_bashes")
                    self._log("Background bashes detected — status set to has_bashes")
            except Exception:
                pass
        except Exception as e:
            import traceback
            self._log(f"FATAL: queue_processor crashed: {e}")
            self._log(traceback.format_exc())
        self._log("WARNING: queue_processor thread exiting")

    def _resolve_triangle(self, to_agent):
        """Auto-resolve bare suffix to full triangle ID based on sender's triangle.
        E.g. sender=388-388, target=188 → 388-188"""
        if '-' not in str(to_agent) and '-' in str(self.agent_id):
            triangle = str(self.agent_id).split('-')[0]
            resolved = f"{triangle}-{to_agent}"
            self._log(f"WARNING: auto-resolved {to_agent} -> {resolved} (sender {self.agent_id} in triangle {triangle})")
            return resolved
        return to_agent

    def _agent_alive(self, agent_id: str) -> bool:
        """Return True if agent_id is valid format and has a running tmux session."""
        if not is_valid_agent_id(agent_id):
            return False
        try:
            result = subprocess.run(
                ['tmux', 'has-session', '-t', f'agent-{agent_id}'],
                capture_output=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def send_to_agent(self, to_agent, prompt):
        """Send message to another agent. Returns 'ok' or 'ko'."""
        if to_agent == 'all':
            sent_count = 0
            for key in self.redis.scan_iter(f'agent:*', count=200):
                parts = key.split(':')
                if len(parts) == 2 and is_valid_agent_id(parts[1]):
                    target_id = parts[1]
                    if target_id != self.agent_id:
                        self.redis.xadd(f"agent:{target_id}:inbox", {
                            'prompt': prompt,
                            'from_agent': self.agent_id,
                            'timestamp': int(time.time())
                        }, maxlen=IO_STREAM_MAXLEN, approximate=True)
                        sent_count += 1
            self._log(f"ok -> broadcast to {sent_count} agents: {prompt[:60]}...")
            return 'ok'
        else:
            to_agent = self._resolve_triangle(to_agent)
            try:
                self.redis.xadd(f"agent:{to_agent}:inbox", {
                    'prompt': prompt,
                    'from_agent': self.agent_id,
                    'timestamp': int(time.time())
                }, maxlen=IO_STREAM_MAXLEN, approximate=True)
            except Exception as e:
                self._log(f"ko send_to_agent {to_agent}: {e}")
                return 'ko'
            if not self._agent_alive(to_agent):
                self._log(f"ko: agent {to_agent} not running — msg in orphan queue")
                return 'ko'
            self._log(f"ok -> agent {to_agent}: {prompt[:60]}...")
            return 'ok'

    def run(self):
        """Main loop - also accepts stdin commands"""
        self._log("Ready. Monitoring Redis and stdin...")

        # Auto-load prompt
        prompt_path = self._find_prompt_file()
        if prompt_path:
            # Read last timestamped entry from .history for context on restart
            last_history = ""
            try:
                hf = Path(prompt_path).parent / f"{self.agent_id}.history"
                if hf.exists() and hf.stat().st_size > 0:
                    for line in reversed(hf.read_text().strip().split('\n')):
                        if line and line[:4].isdigit() and ' | ' in line[:25]:
                            last_history = line
                            break
            except Exception:
                pass

            if self._is_x45_agent(prompt_path):
                files_list = self._get_x45_files(prompt_path)

                if files_list:
                    files_str = ", ".join(files_list)
                    self._log(f"Auto-loading x45 agent: {prompt_path} ({len(files_list)} files)")
                    # Message 1: become the agent
                    self.prompt_queue.put({
                        'prompt': f"Lis ces fichiers dans l'ordre et deviens cet agent : {files_str}",
                        'from_agent': 'auto_init',
                        'msg_id': f"init_{int(time.time())}",
                    })
                    # Message 2: history context (sent after agent has loaded)
                    if last_history:
                        self.prompt_queue.put({
                            'prompt': f"Dernière ligne de ton historique : \"{last_history}\"\nContinue.",
                            'from_agent': 'auto_init',
                            'msg_id': f"init_resume_{int(time.time())}",
                        })
                else:
                    self._log(f"WARNING: x45 dir {prompt_path} found but no system.md or {self.agent_id}-system.md")
            else:
                self._log(f"Auto-loading: {prompt_path}")
                # Message 1: become the agent
                self.prompt_queue.put({
                    'prompt': f"deviens agent {prompt_path}",
                    'from_agent': 'auto_init',
                    'msg_id': f"init_{int(time.time())}",
                })
                # Message 2: history context (sent after agent has loaded)
                if last_history:
                    self.prompt_queue.put({
                        'prompt': f"Dernière ligne de ton historique : \"{last_history}\"\nContinue.",
                        'from_agent': 'auto_init',
                        'msg_id': f"init_resume_{int(time.time())}",
                    })

        # A6 : l'auto-init (ou rien, si pas de prompt) est en queue — le
        # listener Redis peut maintenant livrer pending et nouveaux messages.
        self._auto_init_queued.set()

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
            self.redis.hset(f"agent:{self.agent_id}", "status", "stopped")
            if self._health_server:
                self._health_server.server_close()
            self.logfile.close()

    def _reload_prompt(self):
        """Reload agent prompt file after context compaction (NO /reset — just re-inject prompt)"""
        prompt_path = self._find_prompt_file()
        if prompt_path:
            self._log(f"RELOAD: {prompt_path} (re-inject prompt, no /reset)")
            self.messages_since_reload = 0

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
            # x45/z21: {id}.md entry point (symlink to AGENT.md)
            x45_entry = parent_dir / f"{self.agent_id}.md"
            if x45_entry.exists():
                return str(x45_entry)

            # x45/z21: {id}-system.md
            x45_system = parent_dir / f"{self.agent_id}-system.md"
            if x45_system.exists():
                return str(parent_dir)

            # old x45: system.md
            system_md = parent_dir / "system.md"
            if system_md.exists():
                return str(parent_dir)

            # mono: flat .md file inside directory (e.g. 900-architect-chat/900-architect-chat.md)
            mono_matches = list(parent_dir.glob(f"{parent_id}-*.md"))
            if mono_matches:
                return str(mono_matches[0])

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

        for candidate in [p.parent / "RULES.md", p / "RULES.md"]:
            if candidate.exists():
                files_list.append(str(candidate))
                break

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
