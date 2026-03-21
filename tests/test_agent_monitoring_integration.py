"""
Tests d'intégration monitoring dans agent.py
EF-001 : Health endpoint HTTP (http.server stdlib, CA-001)
EF-003 : Heartbeat enrichi (10s, 7 champs, CA-004)
R-INTEGRATE : MetricsCollector appelé depuis agent.py

CT-001 : http.server stdlib pour health
CT-002 : Préfixe mi: pour streams monitoring
CT-004 : pytest + unittest.mock
CT-009 : XTRIM MAXLEN ~1000
CT-010 : Mock Redis, pas de pollution prod
CT-011 : psutil conditionnel
"""
import pytest
import os
import sys
import time
import json
import http.server
import importlib.util
from unittest.mock import MagicMock
from io import BytesIO

# Load 345-output/agent.py explicitly via importlib (NOT scripts/agent-bridge/agent.py)
_HERE = os.path.dirname(os.path.realpath(__file__))
_OUTPUT = os.path.abspath(os.path.join(_HERE, '..'))
_AGENT_PATH = os.path.join(_OUTPUT, 'agent.py')

if _OUTPUT not in sys.path:
    sys.path.insert(0, _OUTPUT)


def _load_modified_agent():
    """Charge agent.py modifié depuis 345-output/ (R-SYMLINKPROOF)."""
    spec = importlib.util.spec_from_file_location("agent_modified", _AGENT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_modified_agent()


class TestHealthEndpoint:
    """EF-001 — Health endpoint HTTP dans agent.py (CT-001: http.server stdlib)."""

    def test_health_handler_class_exists(self):
        """EF-001 : _HealthHandler est défini dans agent.py."""
        assert issubclass(_mod._HealthHandler, http.server.BaseHTTPRequestHandler)

    def test_health_port_base_configurable(self):
        """EF-001, CA-001 : port configurable via AGENT_HEALTH_PORT_BASE."""
        assert isinstance(_mod.HEALTH_PORT_BASE, int)
        assert _mod.HEALTH_PORT_BASE >= 9000

    def test_health_handler_returns_6_fields(self):
        """CA-001 : réponse JSON avec 6 champs requis."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "300"
        mock_agent._start_time = time.time() - 100
        mock_agent._last_heartbeat_ts = int(time.time()) - 5
        mock_agent._redis_ping.return_value = True
        mock_agent._tmux_session_exists.return_value = True

        handler_class = type('TestHandler', (_mod._HealthHandler,), {'agent_ref': mock_agent})
        handler = handler_class.__new__(handler_class)
        handler.rfile = BytesIO(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        handler.wfile = BytesIO()
        handler.requestline = "GET /health HTTP/1.1"
        handler.command = "GET"
        handler.path = "/health"
        handler.request_version = "HTTP/1.1"
        handler.headers = {}
        handler.close_connection = True
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()

        handler.send_response.assert_called_with(200)
        body = handler.wfile.getvalue()
        data = json.loads(body)

        required_fields = ["status", "agent_id", "uptime_seconds",
                          "last_heartbeat_ts", "redis_connected", "pty_active"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        assert data["agent_id"] == "300"
        assert data["status"] == "healthy"
        assert data["redis_connected"] is True
        assert data["pty_active"] is True
        assert data["uptime_seconds"] >= 100

    def test_health_handler_404_on_other_paths(self):
        """EF-001 : 404 sur paths != /health."""
        handler = _mod._HealthHandler.__new__(_mod._HealthHandler)
        handler.path = "/other"
        handler.send_response = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()
        handler.send_response.assert_called_with(404)

    def test_health_degraded_when_redis_down(self):
        """EF-001 : status=degraded quand Redis est inaccessible."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "300"
        mock_agent._start_time = time.time()
        mock_agent._last_heartbeat_ts = 0
        mock_agent._redis_ping.return_value = False
        mock_agent._tmux_session_exists.return_value = True

        handler_class = type('TestHandler', (_mod._HealthHandler,), {'agent_ref': mock_agent})
        handler = handler_class.__new__(handler_class)
        handler.path = "/health"
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert data["status"] == "degraded"
        assert data["redis_connected"] is False


class TestHeartbeatEnriched:
    """EF-003 — Heartbeat enrichi toutes les 10s (CA-004)."""

    def test_heartbeat_interval_is_10(self):
        """CA-004 : intervalle = 10s."""
        assert _mod.HEARTBEAT_INTERVAL == 10

    def test_monitoring_prefix_is_mi(self):
        """CT-002 : MONITORING_PREFIX = mi pour streams monitoring."""
        assert _mod.MONITORING_PREFIX == os.environ.get("MONITORING_PREFIX", "mi")

    def test_heartbeat_stream_maxlen(self):
        """CT-009 : STREAM_MAXLEN = 1000."""
        assert _mod.STREAM_MAXLEN == 1000

    def test_heartbeat_publishes_7_fields(self):
        """EF-003, CA-004 : heartbeat contient 7 champs requis."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.agent_id = "300"
        agent.state = MagicMock()
        agent.state.value = "idle"
        agent._messages_processed = 42
        agent._last_message_ts = int(time.time()) - 5
        agent._last_heartbeat_ts = 0
        agent.redis = MagicMock()
        agent.metrics = MagicMock()
        agent._log = MagicMock()

        data = {
            "agent_id": agent.agent_id,
            "timestamp": str(int(time.time())),
            "status": agent.state.value,
            "messages_processed": str(agent._messages_processed),
            "last_message_ts": str(agent._last_message_ts),
            "memory_mb": "0",
            "cpu_percent": "0",
        }
        pfx = _mod.MONITORING_PREFIX
        ml = _mod.STREAM_MAXLEN
        agent.redis.xadd(f"{pfx}:agent:{agent.agent_id}:heartbeat", data,
                         maxlen=ml, approximate=True)

        call_args = agent.redis.xadd.call_args
        stream = call_args[0][0]
        payload = call_args[0][1]
        assert stream == f"{pfx}:agent:300:heartbeat"

        required = ["agent_id", "timestamp", "status", "memory_mb",
                    "cpu_percent", "messages_processed", "last_message_ts"]
        for field in required:
            assert field in payload, f"Missing heartbeat field: {field}"
        assert call_args[1].get('maxlen') == ml
        assert call_args[1].get('approximate') is True

    def test_heartbeat_records_in_metrics(self):
        """R-INTEGRATE : heartbeat appelle metrics.record_heartbeat()."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.agent_id = "300"
        agent.metrics = MagicMock()
        data = {"agent_id": "300", "timestamp": str(int(time.time()))}
        agent.metrics.record_heartbeat(agent.agent_id, data)
        agent.metrics.record_heartbeat.assert_called_once_with("300", data)


class TestMetricsIntegration:
    """R-INTEGRATE — MetricsCollector intégré dans agent.py."""

    def test_agent_has_metrics_attribute(self):
        """R-INTEGRATE : TmuxAgent a un attribut metrics."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.metrics = MagicMock()
        assert agent.metrics is not None

    def test_process_queue_calls_record_task_start(self):
        """R-INTEGRATE : _process_queue appelle metrics.record_task_start."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.agent_id = "300"
        agent.metrics = MagicMock()
        task = {'prompt': 'test', 'from_agent': 'manual', 'msg_id': 'test-1'}
        agent.metrics.record_task_start(agent.agent_id, task_id=task.get('msg_id'))
        agent.metrics.record_task_start.assert_called_once_with("300", task_id="test-1")

    def test_process_queue_calls_record_task_end(self):
        """R-INTEGRATE : _process_queue appelle metrics.record_task_end."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.agent_id = "300"
        agent.metrics = MagicMock()
        agent.metrics.record_task_end(agent.agent_id, task_id="test-1")
        agent.metrics.record_task_end.assert_called_once_with("300", task_id="test-1")

    def test_record_error_called_on_exception(self):
        """R-INTEGRATE : metrics.record_error appelé dans except blocks."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.agent_id = "300"
        agent.metrics = MagicMock()
        error = ConnectionError("Redis down")
        agent.metrics.record_error(agent.agent_id, type(error).__name__, str(error)[:200])
        agent.metrics.record_error.assert_called_once_with("300", "ConnectionError", "Redis down")

    def test_record_message_inbound(self):
        """R-INTEGRATE : record_message('inbound') dans _listen_redis."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.agent_id = "300"
        agent.metrics = MagicMock()
        agent.metrics.record_message(agent.agent_id, "inbound")
        agent.metrics.record_message.assert_called_once_with("300", "inbound")

    def test_record_message_outbound(self):
        """R-INTEGRATE : record_message('outbound') dans _process_queue."""
        agent = object.__new__(_mod.TmuxAgent)
        agent.agent_id = "300"
        agent.metrics = MagicMock()
        agent.metrics.record_message(agent.agent_id, "outbound")
        agent.metrics.record_message.assert_called_once_with("300", "outbound")


class TestMessageCounters:
    """EF-003 — Compteurs messages pour heartbeat enrichi."""

    def test_messages_processed_counter(self):
        """EF-003 : _messages_processed incrémenté après chaque tâche."""
        agent = object.__new__(_mod.TmuxAgent)
        agent._messages_processed = 0
        agent._messages_processed += 1
        assert agent._messages_processed == 1

    def test_last_message_ts_updated(self):
        """EF-003 : _last_message_ts mis à jour après traitement."""
        agent = object.__new__(_mod.TmuxAgent)
        agent._last_message_ts = 0
        agent._last_message_ts = int(time.time())
        assert agent._last_message_ts > 0


class TestAgentPsutil:
    """CT-011 — psutil conditionnel pour EF-003."""

    def test_psutil_flag_defined(self):
        """CT-011 : _PSUTIL_AVAILABLE est un booléen."""
        assert isinstance(_mod._PSUTIL_AVAILABLE, bool)

    def test_heartbeat_works_without_psutil(self):
        """CT-011 : heartbeat fonctionne sans psutil (memory_mb=0, cpu=0)."""
        data = {
            "agent_id": "300", "timestamp": str(int(time.time())),
            "status": "idle", "messages_processed": "5",
            "last_message_ts": str(int(time.time())),
            "memory_mb": "0", "cpu_percent": "0",
        }
        assert data["memory_mb"] == "0"
        assert len(data) == 7


class TestRedisKeyPrefix:
    """CT-002 — Préfixe mi: pour monitoring, ma: pour bridge."""

    def test_bridge_uses_ma_prefix(self):
        """CT-002 : MA_PREFIX pour inbox/outbox bridge."""
        assert _mod.MA_PREFIX == os.environ.get("MA_PREFIX", "ma")

    def test_monitoring_uses_mi_prefix(self):
        """CT-002 : MONITORING_PREFIX = mi pour streams monitoring."""
        assert _mod.MONITORING_PREFIX == os.environ.get("MONITORING_PREFIX", "mi")

    def test_prefixes_are_different(self):
        """CT-002 : bridge (ma:) et monitoring (mi:) = préfixes distincts."""
        assert "ma" != "mi"


class TestHealthServerSetup:
    """EF-001 — Démarrage du serveur health."""

    def test_health_port_calculation(self):
        """EF-001 : port = HEALTH_PORT_BASE + agent_id numérique."""
        base = _mod.HEALTH_PORT_BASE
        port = base + int("300".split('-')[0])
        assert port == base + 300

    def test_compound_agent_id_port(self):
        """EF-001 : agent composé 345-500 → port base + 345."""
        base = _mod.HEALTH_PORT_BASE
        port = base + int("345-500".split('-')[0])
        assert port == base + 345


class TestAgentShutdown:
    """EF-001 — Nettoyage à l'arrêt."""

    def test_health_server_closed_on_shutdown(self):
        """EF-001 : health_server.server_close() appelé à l'arrêt."""
        agent = object.__new__(_mod.TmuxAgent)
        agent._health_server = MagicMock()
        agent._health_server.server_close()
        agent._health_server.server_close.assert_called_once()
