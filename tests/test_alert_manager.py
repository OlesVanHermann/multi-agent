"""
Tests pour alert_manager.py — Tâche 004
Couvre : détection stale, stuck, error burst, alertes actives, acquittement

CT-002 : pytest
CT-004 : Mock Redis
"""
import pytest
import json
import time
from unittest.mock import MagicMock, patch, call
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from monitoring.alert_manager import (
    AlertManager, AlertLevel, AlertType,
    DEFAULT_STALE_THRESHOLD, DEFAULT_STUCK_CYCLES
)


class TestAlertManagerInit:
    """Tests d'initialisation."""

    def test_init_defaults(self):
        """Seuils par défaut configurés."""
        redis = MagicMock()
        am = AlertManager(redis)
        assert am.stale_threshold == DEFAULT_STALE_THRESHOLD
        assert am.stuck_cycles == DEFAULT_STUCK_CYCLES

    def test_init_custom_thresholds(self):
        """Seuils personnalisés acceptés."""
        redis = MagicMock()
        am = AlertManager(redis, stale_threshold=60, stuck_cycles=3)
        assert am.stale_threshold == 60
        assert am.stuck_cycles == 3

    def test_init_custom_prefix(self):
        """Préfixe personnalisé pour isolation (CT-004)."""
        redis = MagicMock()
        am = AlertManager(redis, prefix="test")
        assert am.prefix == "test"


class TestCheckAgentStale:
    """Tests détection agent stale (Tâche 004 §1)."""

    def test_stale_agent_detected(self):
        """Agent sans heartbeat depuis > seuil déclenche alerte."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "status": "busy",
            "last_seen": str(int(time.time()) - 300)  # 5 min ago
        }
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"
        am = AlertManager(redis, prefix="test", stale_threshold=120)

        alert = am.check_agent_stale("345")

        assert alert is not None
        assert alert["type"] == AlertType.AGENT_STALE
        assert alert["agent_id"] == "345"
        assert "300" in alert["message"] or "stale" in alert["message"]

    def test_fresh_agent_no_alert(self):
        """Agent avec heartbeat récent ne déclenche pas d'alerte."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "status": "idle",
            "last_seen": str(int(time.time()) - 10)  # 10s ago
        }
        am = AlertManager(redis, prefix="test", stale_threshold=120)

        alert = am.check_agent_stale("345")

        assert alert is None

    def test_stale_critical_threshold(self):
        """Agent très stale (3x seuil) → alerte CRITICAL."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "status": "busy",
            "last_seen": str(int(time.time()) - 400)  # 400s, > 3*120
        }
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"
        am = AlertManager(redis, prefix="test", stale_threshold=120)

        alert = am.check_agent_stale("345")

        assert alert is not None
        assert alert["level"] == AlertLevel.CRITICAL

    def test_no_agent_data_no_alert(self):
        """Agent inconnu ne déclenche pas d'alerte."""
        redis = MagicMock()
        redis.hgetall.return_value = {}
        am = AlertManager(redis, prefix="test")

        alert = am.check_agent_stale("999")

        assert alert is None

    def test_no_last_seen_no_alert(self):
        """Agent sans last_seen ne déclenche pas d'alerte."""
        redis = MagicMock()
        redis.hgetall.return_value = {"status": "idle"}
        am = AlertManager(redis, prefix="test")

        alert = am.check_agent_stale("345")

        assert alert is None


class TestCheckAgentStuck:
    """Tests détection agent bloqué (Tâche 004 §2)."""

    def test_stuck_agent_detected(self):
        """Agent sans progression depuis > N cycles déclenche alerte."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "cycles_completed": "3",
            "last_cycle_time": str(time.time() - 7200),  # 2h ago
            "avg_latency": "60"  # 60s avg → expected_cycle = 600s
        }
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"
        am = AlertManager(redis, prefix="test", stuck_cycles=2)

        alert = am.check_agent_stuck("345")

        # 7200 / 600 = 12 cycles elapsed > 2
        assert alert is not None
        assert alert["type"] == AlertType.AGENT_STUCK

    def test_active_agent_no_alert(self):
        """Agent actif ne déclenche pas d'alerte stuck."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "cycles_completed": "5",
            "last_cycle_time": str(time.time() - 60),  # 1 min ago
            "avg_latency": "30"
        }
        am = AlertManager(redis, prefix="test", stuck_cycles=2)

        alert = am.check_agent_stuck("345")

        assert alert is None

    def test_no_metrics_no_alert(self):
        """Agent sans métriques ne déclenche pas d'alerte stuck."""
        redis = MagicMock()
        redis.hgetall.return_value = {}
        am = AlertManager(redis, prefix="test")

        alert = am.check_agent_stuck("345")

        assert alert is None

    def test_no_last_cycle_no_alert(self):
        """Agent sans cycle précédent ne déclenche pas d'alerte."""
        redis = MagicMock()
        redis.hgetall.return_value = {"cycles_completed": "0"}
        am = AlertManager(redis, prefix="test")

        alert = am.check_agent_stuck("345")

        assert alert is None


class TestCheckErrorBurst:
    """Tests détection burst d'erreurs."""

    def test_error_burst_detected(self):
        """Burst d'erreurs récent déclenche alerte CRITICAL."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "errors_total": "10",
            "last_error_time": str(time.time() - 30),  # 30s ago
            "last_error_type": "ConnectionError"
        }
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"
        am = AlertManager(redis, prefix="test", error_burst_threshold=5, error_burst_window=300)

        alert = am.check_error_burst("345")

        assert alert is not None
        assert alert["type"] == AlertType.ERROR_BURST
        assert alert["level"] == AlertLevel.CRITICAL

    def test_old_errors_no_alert(self):
        """Erreurs anciennes ne déclenchent pas d'alerte burst."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "errors_total": "10",
            "last_error_time": str(time.time() - 600),  # 10 min ago, > window
        }
        am = AlertManager(redis, prefix="test", error_burst_threshold=5, error_burst_window=300)

        alert = am.check_error_burst("345")

        assert alert is None

    def test_few_errors_no_alert(self):
        """Peu d'erreurs ne déclenchent pas d'alerte burst."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "errors_total": "2",
            "last_error_time": str(time.time() - 10),
        }
        am = AlertManager(redis, prefix="test", error_burst_threshold=5)

        alert = am.check_error_burst("345")

        assert alert is None


class TestCheckAllAgents:
    """Tests du check global."""

    def test_check_all_agents(self):
        """Check global retourne les alertes de tous les agents."""
        redis = MagicMock()

        # scan_iter retourne des clés agent
        redis.scan_iter.return_value = ["test:agent:345", "test:agent:300"]

        # Agent 345: stale
        def mock_hgetall(key):
            if key == "test:agent:345":
                return {"status": "busy", "last_seen": str(int(time.time()) - 500)}
            elif key == "test:agent:300":
                return {"status": "idle", "last_seen": str(int(time.time()) - 10)}
            return {}

        redis.hgetall.side_effect = mock_hgetall
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"

        am = AlertManager(redis, prefix="test", stale_threshold=120)
        alerts = am.check_all_agents()

        # Au moins 1 alerte pour 345 (stale)
        stale_alerts = [a for a in alerts if a["agent_id"] == "345" and a["type"] == AlertType.AGENT_STALE]
        assert len(stale_alerts) >= 1

    def test_check_all_no_agents(self):
        """Check global sans agents retourne liste vide."""
        redis = MagicMock()
        redis.scan_iter.return_value = []
        am = AlertManager(redis, prefix="test")

        alerts = am.check_all_agents()

        assert alerts == []


class TestAlertPublishing:
    """Tests de publication des alertes."""

    def test_alert_stored_in_redis(self):
        """Alerte stockée dans hash Redis."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "status": "busy",
            "last_seen": str(int(time.time()) - 300)
        }
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"

        am = AlertManager(redis, prefix="test", stale_threshold=120)
        alert = am.check_agent_stale("345")

        assert alert is not None
        # Vérifier que hset a été appelé pour l'alerte
        hset_calls = [c for c in redis.hset.call_args_list
                      if "test:alerts:" in str(c)]
        assert len(hset_calls) >= 1

    def test_alert_added_to_active_set(self):
        """Alerte ajoutée au set des alertes actives."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "status": "busy",
            "last_seen": str(int(time.time()) - 300)
        }
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"

        am = AlertManager(redis, prefix="test", stale_threshold=120)
        am.check_agent_stale("345")

        redis.sadd.assert_called()

    def test_alert_published_to_stream(self):
        """Alerte publiée dans le stream Redis (CT-006)."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "status": "busy",
            "last_seen": str(int(time.time()) - 300)
        }
        redis.sadd.return_value = 1
        redis.xadd.return_value = "1-0"

        am = AlertManager(redis, prefix="test", stale_threshold=120)
        am.check_agent_stale("345")

        # Vérifier xadd avec format CT-006 (from, type, payload, timestamp)
        xadd_calls = redis.xadd.call_args_list
        assert len(xadd_calls) >= 1
        stream_key, data = xadd_calls[0][0]
        assert data["from"] == "alert_manager"
        assert "alert:" in data["type"]
        assert "timestamp" in data


class TestGetActiveAlerts:
    """Tests de récupération des alertes actives."""

    def test_get_active_alerts(self):
        """Récupération et parsing des alertes actives."""
        redis = MagicMock()
        redis.smembers.return_value = {"345:agent_stale:1000"}
        redis.hgetall.return_value = {
            "agent_id": "345",
            "type": "agent_stale",
            "level": "warning",
            "message": "Agent stale",
            "details": '{"age_seconds": 300}',
            "timestamp": "1000.0",
            "acknowledged": "false"
        }

        am = AlertManager(redis, prefix="test")
        alerts = am.get_active_alerts()

        assert len(alerts) == 1
        assert alerts[0]["agent_id"] == "345"
        assert alerts[0]["details"]["age_seconds"] == 300
        assert alerts[0]["timestamp"] == 1000.0

    def test_get_active_alerts_empty(self):
        """Pas d'alertes actives retourne liste vide."""
        redis = MagicMock()
        redis.smembers.return_value = set()
        am = AlertManager(redis, prefix="test")

        alerts = am.get_active_alerts()
        assert alerts == []


class TestAcknowledgeAlert:
    """Tests d'acquittement des alertes."""

    def test_acknowledge_existing_alert(self):
        """Acquittement d'une alerte existante."""
        redis = MagicMock()
        redis.srem.return_value = 1
        am = AlertManager(redis, prefix="test")

        result = am.acknowledge_alert("345:agent_stale:1000")

        assert result is True
        redis.srem.assert_called_once()
        redis.hset.assert_called_once()

    def test_acknowledge_nonexistent_alert(self):
        """Acquittement d'une alerte inexistante retourne False."""
        redis = MagicMock()
        redis.srem.return_value = 0
        am = AlertManager(redis, prefix="test")

        result = am.acknowledge_alert("nonexistent")

        assert result is False


class TestClearAlerts:
    """Tests de nettoyage des alertes."""

    def test_clear_all_alerts(self):
        """Suppression de toutes les alertes."""
        redis = MagicMock()
        redis.smembers.return_value = {"alert1", "alert2"}
        am = AlertManager(redis, prefix="test")

        am.clear_all_alerts()

        assert redis.delete.call_count >= 3  # 2 alerts + active set
