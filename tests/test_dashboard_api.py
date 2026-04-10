"""
Tests pour dashboard_api.py — Tâche 004
Couvre : endpoints métriques, alertes, résumé, check

CT-002 : pytest
CT-004 : Mock Redis
CT-001 : FastAPI + httpx async
"""
import pytest
import json
import time
from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from fastapi import FastAPI
    import httpx
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


def _make_mock_redis():
    """Crée un mock Redis avec comportement par défaut."""
    redis = MagicMock()
    redis.hgetall.return_value = {}
    redis.hget.return_value = None
    redis.scan_iter.return_value = []
    redis.smembers.return_value = set()
    redis.lrange.return_value = []
    return redis


def _make_app(redis):
    """Crée une app FastAPI avec le router monitoring."""
    from monitoring.dashboard_api import create_monitoring_router
    app = FastAPI()
    router = create_monitoring_router(redis, prefix="test")
    app.include_router(router)
    return app


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestDashboardAPIMetrics:
    """Tests des endpoints métriques (Tâche 004 §1, §3)."""

    @pytest.mark.anyio
    async def test_get_all_metrics_empty(self):
        """GET /metrics sans agents retourne liste vide."""
        redis = _make_mock_redis()
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/metrics")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0
            assert data["agents"] == {}

    @pytest.mark.anyio
    async def test_get_all_metrics_with_agents(self):
        """GET /metrics avec agents retourne les métriques."""
        redis = _make_mock_redis()
        redis.scan_iter.return_value = ["test:metrics:345", "test:metrics:300"]
        redis.hgetall.return_value = {"tasks_total": "5", "avg_latency": "2.0"}
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/metrics")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2

    @pytest.mark.anyio
    async def test_get_agent_metrics(self):
        """GET /metrics/{id} retourne les métriques d'un agent."""
        redis = _make_mock_redis()
        redis.hgetall.return_value = {
            "tasks_total": "10",
            "avg_latency": "1.5",
            "errors_total": "2"
        }
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/metrics/345")
            assert resp.status_code == 200
            data = resp.json()
            assert data["tasks_total"] == 10
            assert data["agent_id"] == "345"

    @pytest.mark.anyio
    async def test_get_agent_metrics_not_found(self):
        """GET /metrics/{id} agent inexistant retourne 404."""
        redis = _make_mock_redis()
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/metrics/999")
            assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_get_agent_latency(self):
        """GET /metrics/{id}/latency retourne l'historique."""
        redis = _make_mock_redis()
        redis.lrange.return_value = [
            json.dumps({"latency": 1.0, "timestamp": 1000, "task_id": "a", "success": True}),
            json.dumps({"latency": 2.0, "timestamp": 1001, "task_id": "b", "success": True})
        ]
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/metrics/345/latency")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2
            assert data["history"][0]["latency"] == 1.0


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestDashboardAPIAlerts:
    """Tests des endpoints alertes (Tâche 004 §2)."""

    @pytest.mark.anyio
    async def test_get_alerts_empty(self):
        """GET /alerts sans alertes retourne liste vide."""
        redis = _make_mock_redis()
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/alerts")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0

    @pytest.mark.anyio
    async def test_get_alerts_with_data(self):
        """GET /alerts avec alertes actives."""
        redis = _make_mock_redis()
        redis.smembers.return_value = {"345:agent_stale:1000"}
        redis.hgetall.return_value = {
            "agent_id": "345",
            "type": "agent_stale",
            "level": "warning",
            "message": "Agent stale",
            "details": '{}',
            "timestamp": "1000.0",
            "acknowledged": "false"
        }
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/alerts")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert data["alerts"][0]["agent_id"] == "345"

    @pytest.mark.anyio
    async def test_acknowledge_alert(self):
        """POST /alerts/{id}/ack acquitte une alerte."""
        redis = _make_mock_redis()
        redis.srem.return_value = 1
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/monitoring/alerts/345:agent_stale:1000/ack")
            assert resp.status_code == 200
            assert resp.json()["acknowledged"] is True

    @pytest.mark.anyio
    async def test_acknowledge_alert_not_found(self):
        """POST /alerts/{id}/ack alerte inexistante retourne 404."""
        redis = _make_mock_redis()
        redis.srem.return_value = 0
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/monitoring/alerts/nonexistent/ack")
            assert resp.status_code == 404


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestDashboardAPISummary:
    """Tests de l'endpoint résumé (Tâche 004 §3)."""

    @pytest.mark.anyio
    async def test_get_summary_empty(self):
        """GET /summary sans données retourne les champs avec zéros."""
        redis = _make_mock_redis()
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert data["agents_monitored"] == 0
            assert data["total_tasks_completed"] == 0
            assert data["avg_score"] is None
            assert "timestamp" in data

    @pytest.mark.anyio
    async def test_get_summary_with_data(self):
        """GET /summary avec données agrège correctement."""
        redis = _make_mock_redis()
        redis.scan_iter.return_value = ["test:metrics:345"]
        redis.hgetall.side_effect = lambda key: {
            "test:metrics:345": {
                "tasks_total": "10",
                "cycles_completed": "3",
                "avg_score": "95.0",
                "avg_latency": "2.5",
                "messages_this_hour": "50"
            },
            "test:metrics:global": {
                "total_tasks": "10",
                "total_errors": "1",
                "total_messages": "50"
            }
        }.get(key, {})
        redis.smembers.return_value = set()
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert data["agents_monitored"] == 1
            assert data["avg_score"] == 95.0
            assert data["messages_per_hour"] == 50


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestDashboardAPICheck:
    """Tests de l'endpoint check."""

    @pytest.mark.anyio
    async def test_run_check(self):
        """POST /check lance un check et retourne les alertes."""
        redis = _make_mock_redis()
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/monitoring/check")
            assert resp.status_code == 200
            data = resp.json()
            assert "alerts_detected" in data
            assert "timestamp" in data


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestDashboardAPIEF006:
    """EF-006, CA-007 : Tests complémentaires server.py monitoring (C5)."""

    @pytest.mark.anyio
    async def test_get_agent_latency_empty(self):
        """EF-006, CA-007 : latency endpoint sans données retourne historique vide."""
        redis = _make_mock_redis()
        redis.lrange.return_value = []
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/monitoring/metrics/999/latency")
            assert resp.status_code == 200
            data = resp.json()
            assert data["agent_id"] == "999"
            assert data["count"] == 0
            assert data["history"] == []

    @pytest.mark.anyio
    async def test_redis_unavailable_metrics_graceful(self):
        """EF-006, CA-007 : Redis indisponible → réponse 500, pas de crash."""
        redis = _make_mock_redis()
        redis.scan_iter.side_effect = ConnectionError("Redis unavailable")
        app = _make_app(redis)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/monitoring/metrics")
            assert resp.status_code == 500

    @pytest.mark.anyio
    async def test_run_check_with_alerts_detected(self):
        """EF-006, CA-007 : check détecte alertes et les retourne."""
        redis = _make_mock_redis()
        redis.scan_iter.return_value = ["test:metrics:345"]
        redis.hgetall.return_value = {
            "tasks_total": "0",
            "last_activity": str(int(time.time()) - 3600)
        }
        app = _make_app(redis)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/monitoring/check")
            assert resp.status_code == 200
            data = resp.json()
            assert "alerts_detected" in data
            assert isinstance(data["alerts_detected"], int)
            assert "alerts" in data
            assert "timestamp" in data
