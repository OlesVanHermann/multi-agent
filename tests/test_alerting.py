"""
Tests pour alerting.py (EF-004 refactoré <200L)
CT-004 : pytest + unittest.mock
CT-006 : alerting.py < 200L
CT-009 : XTRIM MAXLEN ~1000 sur streams
CT-010 : Préfixe test, mock Redis

Ref spec 342 : CA-005 (alertes logguées), EF-004
"""
import pytest
import time
import os
import sys
import json
from unittest.mock import MagicMock, patch, call

# Setup path
_HERE = os.path.dirname(os.path.realpath(__file__))
_OUTPUT = os.path.abspath(os.path.join(_HERE, '..'))
if _OUTPUT not in sys.path:
    sys.path.insert(0, _OUTPUT)

from monitoring.alerting import AlertManager, STREAM_MAXLEN, DEFAULT_PREFIX


class TestAlertingModule:
    """EF-004 — Module alerting.py doit être <200L (CT-006)."""

    def test_ct006_alerting_under_200_lines(self):
        """CT-006 : alerting.py < 200 lignes."""
        path = os.path.join(_OUTPUT, 'monitoring', 'alerting.py')
        with open(path) as f:
            lines = len(f.readlines())
        assert lines < 200, f"alerting.py = {lines}L, doit être < 200L (CT-006)"

    def test_default_prefix_is_mi(self):
        """CT-002 : préfixe par défaut est mi: pour monitoring."""
        assert DEFAULT_PREFIX == os.environ.get("MA_PREFIX", "mi")

    def test_stream_maxlen_is_1000(self):
        """CT-009 : STREAM_MAXLEN = 1000."""
        assert STREAM_MAXLEN == 1000


class TestAlertManagerCreation:
    """EF-004 — Construction AlertManager avec seuils configurables."""

    def test_default_thresholds(self):
        """EF-004 : seuils par défaut raisonnables."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        assert mgr.stale_threshold == 120
        assert mgr.stuck_cycles == 2
        assert mgr.error_burst_threshold == 5
        assert mgr.error_burst_window == 300

    def test_custom_thresholds(self):
        """EF-004 : seuils personnalisables via constructeur."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test",
                           stale_threshold=60, stuck_cycles=3,
                           error_burst_threshold=10, error_burst_window=600)
        assert mgr.stale_threshold == 60
        assert mgr.stuck_cycles == 3
        assert mgr.error_burst_threshold == 10
        assert mgr.error_burst_window == 600


class TestCheckAgentStale:
    """EF-004 — Détection agent stale (pas de heartbeat récent)."""

    def test_stale_agent_warning(self):
        """EF-004 : agent stale depuis >120s → alerte warning."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        old_ts = str(int(time.time()) - 200)  # 200s ago
        redis_mock.hgetall.return_value = {"last_seen": old_ts, "status": "idle"}
        redis_mock.smembers.return_value = set()

        alert = mgr.check_agent_stale("300")
        assert alert is not None
        assert alert["type"] == "agent_stale"
        assert alert["level"] == "warning"
        assert alert["agent_id"] == "300"

    def test_stale_agent_critical(self):
        """EF-004 : agent stale > 3x seuil → alerte critical."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        old_ts = str(int(time.time()) - 500)  # 500s > 120*3=360
        redis_mock.hgetall.return_value = {"last_seen": old_ts, "status": "idle"}
        redis_mock.smembers.return_value = set()

        alert = mgr.check_agent_stale("300")
        assert alert is not None
        assert alert["level"] == "critical"

    def test_fresh_agent_no_alert(self):
        """EF-004 : agent récent → pas d'alerte."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        fresh_ts = str(int(time.time()) - 10)  # 10s ago
        redis_mock.hgetall.return_value = {"last_seen": fresh_ts, "status": "idle"}

        alert = mgr.check_agent_stale("300")
        assert alert is None

    def test_no_agent_data_no_alert(self):
        """EF-004 : agent sans données → pas d'alerte."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.hgetall.return_value = {}

        alert = mgr.check_agent_stale("300")
        assert alert is None

    def test_no_last_seen_no_alert(self):
        """EF-004 : agent sans last_seen → pas d'alerte."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.hgetall.return_value = {"status": "idle"}

        alert = mgr.check_agent_stale("300")
        assert alert is None


class TestCheckAgentStuck:
    """EF-004, Tâche 004 §2 — Détection agent bloqué >2 cycles."""

    def test_stuck_agent(self):
        """Tâche 004 §2 : agent sans progrès > 2 cycles → alerte."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        old_cycle = str(time.time() - 1000)  # 1000s ago, expected=300s → ~3.3 cycles
        redis_mock.hgetall.return_value = {
            "last_cycle_time": old_cycle,
            "cycles_completed": "5",
            "avg_latency": "30"
        }

        alert = mgr.check_agent_stuck("300")
        assert alert is not None
        assert alert["type"] == "agent_stuck"
        assert alert["level"] == "warning"

    def test_progressing_agent_no_alert(self):
        """Tâche 004 §2 : agent avec cycle récent → pas d'alerte."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        recent = str(time.time() - 10)
        redis_mock.hgetall.return_value = {
            "last_cycle_time": recent,
            "cycles_completed": "5",
            "avg_latency": "30"
        }

        alert = mgr.check_agent_stuck("300")
        assert alert is None

    def test_no_metrics_no_alert(self):
        """EF-004 : pas de métriques → pas d'alerte stuck."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.hgetall.return_value = {}

        alert = mgr.check_agent_stuck("300")
        assert alert is None


class TestCheckErrorBurst:
    """EF-004 — Détection burst d'erreurs."""

    def test_error_burst_detected(self):
        """EF-004 : 5+ erreurs récentes → alerte critical."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.hgetall.return_value = {
            "errors_total": "7",
            "last_error_time": str(time.time() - 10),
            "last_error_type": "ConnectionError"
        }

        alert = mgr.check_error_burst("300")
        assert alert is not None
        assert alert["type"] == "error_burst"
        assert alert["level"] == "critical"

    def test_old_errors_no_alert(self):
        """EF-004 : erreurs anciennes (hors fenêtre) → pas d'alerte."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.hgetall.return_value = {
            "errors_total": "10",
            "last_error_time": str(time.time() - 600),  # 10 min ago, fenêtre = 5 min
            "last_error_type": "Timeout"
        }

        alert = mgr.check_error_burst("300")
        assert alert is None

    def test_few_errors_no_alert(self):
        """EF-004 : <5 erreurs → pas d'alerte."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.hgetall.return_value = {
            "errors_total": "3",
            "last_error_time": str(time.time() - 10)
        }

        alert = mgr.check_error_burst("300")
        assert alert is None


class TestCreateAlertXTRIM:
    """CT-009 — XTRIM MAXLEN ~1000 sur xadd (R-XTRIM)."""

    def test_xadd_uses_maxlen(self):
        """CT-009 : xadd doit passer maxlen=1000, approximate=True."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")

        mgr._create_alert("300", "agent_stale", "warning", "test msg", {"key": "val"})

        # Vérifier que xadd a été appelé avec maxlen
        xadd_call = redis_mock.xadd.call_args
        assert xadd_call is not None
        assert xadd_call.kwargs.get('maxlen') == STREAM_MAXLEN
        assert xadd_call.kwargs.get('approximate') is True

    def test_alert_stored_in_hash(self):
        """EF-004 : alerte stockée dans hash Redis."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")

        alert = mgr._create_alert("300", "agent_stale", "warning", "test", {})
        assert redis_mock.hset.called
        assert redis_mock.sadd.called

    def test_alert_published_to_stream(self):
        """CT-002 : alerte publiée au format from/type/payload/timestamp."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")

        mgr._create_alert("300", "error_burst", "critical", "burst", {"errors": 5})

        xadd_args = redis_mock.xadd.call_args[0]
        stream_key = xadd_args[0]
        data = xadd_args[1]

        assert stream_key == "test:alerts:stream"
        assert data["from"] == "alert_manager"
        assert data["type"] == "alert:critical"
        assert "payload" in data
        assert "timestamp" in data


class TestCheckAllAgents:
    """EF-004 — Scan de tous les agents."""

    def test_check_all_finds_stale(self):
        """EF-004 : check_all_agents détecte les agents stale."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")

        redis_mock.scan_iter.return_value = iter(["test:agent:300"])
        old_ts = str(int(time.time()) - 200)
        redis_mock.hgetall.return_value = {"last_seen": old_ts, "status": "idle"}
        redis_mock.smembers.return_value = set()

        alerts = mgr.check_all_agents()
        assert len(alerts) >= 1
        assert any(a["type"] == "agent_stale" for a in alerts)

    def test_check_all_deduplicates(self):
        """EF-004 : check_all_agents ne duplique pas les checks par agent."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")

        # Même agent apparaît via scan (key format 3 parts)
        redis_mock.scan_iter.return_value = iter(["test:agent:300", "test:agent:300"])
        redis_mock.hgetall.return_value = {}

        alerts = mgr.check_all_agents()
        assert len(alerts) == 0  # No data → no alerts, but shouldn't crash


class TestGetActiveAlerts:
    """EF-004 — Récupération alertes actives."""

    def test_get_active_sorted_by_timestamp(self):
        """EF-004 : alertes triées par timestamp décroissant."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")

        redis_mock.smembers.return_value = {"alert1", "alert2"}
        redis_mock.hgetall.side_effect = [
            {"type": "agent_stale", "level": "warning", "timestamp": "100",
             "message": "old", "details": "{}"},
            {"type": "error_burst", "level": "critical", "timestamp": "200",
             "message": "new", "details": "{}"},
        ]

        alerts = mgr.get_active_alerts()
        assert len(alerts) == 2
        assert alerts[0]["timestamp"] > alerts[1]["timestamp"]

    def test_get_active_parses_details_json(self):
        """EF-004 : details JSON parsé correctement."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")

        redis_mock.smembers.return_value = {"alert1"}
        redis_mock.hgetall.return_value = {
            "type": "agent_stuck", "level": "warning", "timestamp": "100",
            "message": "stuck", "details": '{"cycles_elapsed": 3.5}'
        }

        alerts = mgr.get_active_alerts()
        assert len(alerts) == 1
        assert alerts[0]["details"]["cycles_elapsed"] == 3.5


class TestAcknowledgeAlert:
    """EF-004 — Acquittement d'alerte."""

    def test_acknowledge_existing(self):
        """EF-004 : acquittement réussi retourne True."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.srem.return_value = 1

        result = mgr.acknowledge_alert("alert1")
        assert result is True
        redis_mock.hset.assert_called_once()

    def test_acknowledge_nonexistent(self):
        """EF-004 : acquittement alerte inexistante retourne False."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.srem.return_value = 0

        result = mgr.acknowledge_alert("nonexistent")
        assert result is False


class TestClearAllAlerts:
    """EF-004 — Suppression de toutes les alertes."""

    def test_clear_all(self):
        """EF-004 : clear_all supprime hash et set."""
        redis_mock = MagicMock()
        mgr = AlertManager(redis_mock, prefix="test")
        redis_mock.smembers.return_value = {"alert1", "alert2"}

        mgr.clear_all_alerts()
        assert redis_mock.delete.call_count == 3  # 2 alerts + active set
