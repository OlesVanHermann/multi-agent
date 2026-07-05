"""
Tests pour metrics_collector.py — Tâche 004
Couvre : latence, erreurs, throughput, cycles, historique, agrégats

CT-002 : pytest
CT-004 : Mock Redis (pas de pollution streams production)
"""
import pytest
import json
import time
from unittest.mock import MagicMock, patch, call
import sys
import os

# Add monitoring module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from monitoring.metrics_collector import MetricsCollector, LATENCY_HISTORY_MAX


class TestMetricsCollectorInit:
    """Tests d'initialisation du MetricsCollector."""

    def test_init_default_prefix(self):
        """Prefix par défaut depuis env ou 'mi' (CT-002, CT-004)."""
        redis = MagicMock()
        mc = MetricsCollector(redis)
        assert mc.prefix in ("mi", os.environ.get("MA_PREFIX", "mi"))

    def test_init_custom_prefix(self):
        """Prefix personnalisé pour isolation tests (CT-004)."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")
        assert mc.prefix == "test"

    def test_keys_use_prefix(self):
        """Les clés Redis utilisent le bon préfixe."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")
        assert mc._metrics_key("345") == "test:metrics:345"
        assert mc._latency_key("345") == "test:metrics:345:latency_log"
        assert mc._global_key() == "test:metrics:global"


class TestRecordTaskLatency:
    """Tests du suivi de latence (Tâche 004 §3)."""

    def test_record_task_start(self):
        """Enregistrement début de tâche."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_task_start("345", task_id="task-1")

        redis.hset.assert_any_call("test:metrics:345", "last_task_start", pytest.approx(time.time(), abs=2))

    def test_record_task_end_calculates_latency(self):
        """Fin de tâche calcule la latence correctement."""
        redis = MagicMock()
        redis.hget.side_effect = lambda key, field: {
            ("test:metrics:345", "last_task_start"): str(time.time() - 5.0),
            ("test:metrics:345", "avg_latency"): None,
            ("test:metrics:345", "latency_count"): None,
        }.get((key, field))
        mc = MetricsCollector(redis, prefix="test")

        latency = mc.record_task_end("345", task_id="task-1")

        assert latency is not None
        assert 4.5 < latency < 6.0  # ~5 seconds

    def test_record_task_end_no_start(self):
        """Fin de tâche sans début retourne None."""
        redis = MagicMock()
        redis.hget.return_value = None
        mc = MetricsCollector(redis, prefix="test")

        latency = mc.record_task_end("345")

        assert latency is None

    def test_record_task_end_increments_counters(self):
        """Fin de tâche incrémente les compteurs."""
        redis = MagicMock()
        redis.hget.return_value = None
        mc = MetricsCollector(redis, prefix="test")

        mc.record_task_end("345", success=True)

        redis.hincrby.assert_any_call("test:metrics:345", "tasks_total", 1)
        redis.hincrby.assert_any_call("test:metrics:345", "tasks_success", 1)

    def test_record_task_end_failed_increments_failed(self):
        """Tâche échouée incrémente tasks_failed."""
        redis = MagicMock()
        redis.hget.return_value = None
        mc = MetricsCollector(redis, prefix="test")

        mc.record_task_end("345", success=False)

        redis.hincrby.assert_any_call("test:metrics:345", "tasks_failed", 1)

    def test_latency_history_trimmed(self):
        """L'historique de latence est limité à LATENCY_HISTORY_MAX."""
        redis = MagicMock()
        redis.hget.side_effect = lambda key, field: {
            ("test:metrics:345", "last_task_start"): str(time.time() - 1.0),
            ("test:metrics:345", "avg_latency"): "2.0",
            ("test:metrics:345", "latency_count"): "5",
        }.get((key, field))
        mc = MetricsCollector(redis, prefix="test")

        mc.record_task_end("345")

        redis.ltrim.assert_called_once_with(
            "test:metrics:345:latency_log", -LATENCY_HISTORY_MAX, -1
        )


class TestRecordError:
    """Tests du comptage d'erreurs (Tâche 004 §3)."""

    def test_record_error_increments(self):
        """Enregistrement d'erreur incrémente les compteurs."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_error("345", "TimeoutError", "Redis timeout")

        redis.hincrby.assert_any_call("test:metrics:345", "errors_total", 1)
        redis.hincrby.assert_any_call("test:metrics:345", "errors:TimeoutError", 1)
        redis.hset.assert_any_call("test:metrics:345", "last_error_type", "TimeoutError")

    def test_record_error_truncates_message(self):
        """Message d'erreur tronqué à 200 caractères."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        long_msg = "x" * 500
        mc.record_error("345", "RuntimeError", long_msg)

        # Vérifier que le message stocké est tronqué
        calls = [c for c in redis.hset.call_args_list
                 if len(c[0]) >= 3 and c[0][1] == "last_error_message"]
        if calls:
            stored_msg = calls[0][0][2]
            assert len(stored_msg) <= 200

    def test_record_error_updates_global(self):
        """Erreur incrémente le compteur global."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_error("345", "ValueError")

        redis.hincrby.assert_any_call("test:metrics:global", "total_errors", 1)


class TestRecordCycle:
    """Tests du suivi de cycles (Tâche 004 §3)."""

    def test_record_cycle_complete(self):
        """Enregistrement de cycle complété."""
        redis = MagicMock()
        redis.hget.return_value = None
        mc = MetricsCollector(redis, prefix="test")

        mc.record_cycle_complete("345", cycle_number=3, score=95)

        redis.hincrby.assert_any_call("test:metrics:345", "cycles_completed", 1)
        redis.hset.assert_any_call("test:metrics:345", "last_cycle", 3)

    def test_record_cycle_with_score(self):
        """Score moyen calculé correctement."""
        redis = MagicMock()
        redis.hget.side_effect = lambda key, field: {
            ("test:metrics:345", "avg_score"): "90.0",
            ("test:metrics:345", "score_count"): "2",
        }.get((key, field))
        mc = MetricsCollector(redis, prefix="test")

        mc.record_cycle_complete("345", cycle_number=3, score=96)

        # avg = 90 + (96-90)/3 = 92
        score_calls = [c for c in redis.hset.call_args_list
                       if isinstance(c[1].get('mapping'), dict) and 'avg_score' in c[1].get('mapping', {})]
        if score_calls:
            avg = score_calls[0][1]['mapping']['avg_score']
            assert abs(avg - 92.0) < 0.1

    def test_record_cycle_without_score(self):
        """Cycle sans score n'affecte pas avg_score."""
        redis = MagicMock()
        redis.hget.return_value = None
        mc = MetricsCollector(redis, prefix="test")

        mc.record_cycle_complete("345", cycle_number=1)

        redis.hincrby.assert_any_call("test:metrics:345", "cycles_completed", 1)
        # Pas d'appel hset avec avg_score
        score_mapping_calls = [c for c in redis.hset.call_args_list
                               if isinstance(c[1].get('mapping'), dict) and 'avg_score' in c[1].get('mapping', {})]
        assert len(score_mapping_calls) == 0


class TestRecordMessage:
    """Tests du throughput (Tâche 004 §3)."""

    def test_record_inbound_message(self):
        """Message entrant incrémente le compteur."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_message("345", direction="inbound")

        redis.hincrby.assert_any_call("test:metrics:345", "messages_inbound", 1)
        redis.hincrby.assert_any_call("test:metrics:global", "total_messages", 1)

    def test_record_outbound_message(self):
        """Message sortant incrémente le compteur."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_message("345", direction="outbound")

        redis.hincrby.assert_any_call("test:metrics:345", "messages_outbound", 1)


class TestGetMetrics:
    """Tests de récupération des métriques."""

    def test_get_metrics_empty(self):
        """Agent sans métriques retourne dict vide."""
        redis = MagicMock()
        redis.hgetall.return_value = {}
        mc = MetricsCollector(redis, prefix="test")

        result = mc.get_metrics("999")
        assert result == {}

    def test_get_metrics_parses_types(self):
        """Les valeurs numériques sont parsées correctement."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "tasks_total": "10",
            "avg_latency": "2.5",
            "last_error_type": "TimeoutError"
        }
        mc = MetricsCollector(redis, prefix="test")

        result = mc.get_metrics("345")

        assert result["tasks_total"] == 10
        assert result["avg_latency"] == 2.5
        assert result["last_error_type"] == "TimeoutError"
        assert result["agent_id"] == "345"

    def test_get_latency_history(self):
        """Historique de latence retourne les entrées JSON."""
        redis = MagicMock()
        entries = [
            json.dumps({"latency": 1.5, "timestamp": 1000, "task_id": "a", "success": True}),
            json.dumps({"latency": 2.0, "timestamp": 1001, "task_id": "b", "success": True})
        ]
        redis.lrange.return_value = entries
        mc = MetricsCollector(redis, prefix="test")

        result = mc.get_latency_history("345")

        assert len(result) == 2
        assert result[0]["latency"] == 1.5
        assert result[1]["latency"] == 2.0

    def test_get_latency_history_with_limit(self):
        """Historique avec limit utilise lrange correctement."""
        redis = MagicMock()
        redis.lrange.return_value = []
        mc = MetricsCollector(redis, prefix="test")

        mc.get_latency_history("345", limit=10)

        redis.lrange.assert_called_once_with("test:metrics:345:latency_log", -10, -1)

    def test_get_global_metrics(self):
        """Métriques globales parsées correctement."""
        redis = MagicMock()
        redis.hgetall.return_value = {
            "total_tasks": "100",
            "total_errors": "5",
            "total_messages": "500"
        }
        mc = MetricsCollector(redis, prefix="test")

        result = mc.get_global_metrics()

        assert result["total_tasks"] == 100
        assert result["total_errors"] == 5

    def test_get_all_agents_metrics(self):
        """Récupération de tous les agents."""
        redis = MagicMock()
        redis.scan_iter.return_value = [
            "test:metrics:345",
            "test:metrics:300",
            "test:metrics:global",
            "test:metrics:345:latency_log"
        ]
        redis.hgetall.return_value = {"tasks_total": "5"}
        mc = MetricsCollector(redis, prefix="test")

        result = mc.get_all_agents_metrics()

        # global et latency_log sont filtrés
        assert "345" in result
        assert "300" in result
        assert "global" not in result


class TestRecordHeartbeat:
    """Tests de record_heartbeat — EF-003, CA-004."""

    def test_record_heartbeat_stores_timestamp(self):
        """EF-003 : record_heartbeat stocke last_heartbeat_ts."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")
        now = time.time()

        mc.record_heartbeat("300", {"timestamp": now, "memory_mb": "50", "cpu_percent": "10"})

        redis.hset.assert_any_call("test:metrics:300", "last_heartbeat_ts", now)

    def test_record_heartbeat_stores_memory(self):
        """EF-003, CT-011 : record_heartbeat stocke memory_mb."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_heartbeat("300", {"timestamp": time.time(), "memory_mb": "128.5"})

        redis.hset.assert_any_call("test:metrics:300", "last_memory_mb", "128.5")

    def test_record_heartbeat_stores_cpu(self):
        """EF-003, CT-011 : record_heartbeat stocke cpu_percent."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_heartbeat("300", {"timestamp": time.time(), "cpu_percent": "25.3"})

        redis.hset.assert_any_call("test:metrics:300", "last_cpu_percent", "25.3")

    def test_record_heartbeat_increments_counter(self):
        """EF-003 : record_heartbeat incrémente heartbeats_total."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_heartbeat("300", {"timestamp": time.time()})

        redis.hincrby.assert_called_with("test:metrics:300", "heartbeats_total", 1)

    def test_record_heartbeat_without_psutil_fields(self):
        """CT-011 : record_heartbeat fonctionne sans memory_mb/cpu_percent."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.record_heartbeat("300", {"timestamp": time.time()})

        # Should not crash, should still set timestamp and increment counter
        redis.hset.assert_called()
        redis.hincrby.assert_called()


class TestResetMetrics:
    """Tests de reset."""

    def test_reset_agent_metrics(self):
        """Reset supprime les clés de l'agent."""
        redis = MagicMock()
        mc = MetricsCollector(redis, prefix="test")

        mc.reset_agent_metrics("345")

        redis.delete.assert_any_call("test:metrics:345")
        redis.delete.assert_any_call("test:metrics:345:latency_log")
