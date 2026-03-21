"""
dashboard_api.py — Endpoints FastAPI pour le monitoring agents
EF-008 : Extraction monitoring de server.py — CT-007 (<300L)
Tâche 004 — Dashboard temps réel : métriques, alertes, résumé

Endpoints :
  GET /api/monitoring/metrics              — Métriques de tous les agents
  GET /api/monitoring/metrics/{agent_id}   — Métriques d'un agent
  GET /api/monitoring/metrics/{agent_id}/latency — Historique latence
  GET /api/monitoring/alerts               — Alertes actives
  POST /api/monitoring/alerts/{id}/ack     — Acquitter une alerte
  GET /api/monitoring/summary              — Résumé agrégé (CA-009)
  POST /api/monitoring/check               — Lancer un check maintenant

CT-002 : Préfixe mi: pour monitoring
CT-004 : Préfixe configurable, isolation tests
"""

import os
import time

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from .metrics_collector import MetricsCollector
from .alerting import AlertManager


def create_monitoring_router(redis_client, prefix=None):
    """Crée un APIRouter FastAPI — EF-008, CA-009, Tâche 004.

    Usage dans server.py (R-INTEGRATE):
        from monitoring.dashboard_api import create_monitoring_router
        router = create_monitoring_router(redis_client, prefix="mi")
        app.include_router(router)
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI requis pour dashboard_api. pip install fastapi")

    router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
    collector = MetricsCollector(redis_client, prefix=prefix)
    alert_mgr = AlertManager(redis_client, prefix=prefix)

    @router.get("/metrics")
    def get_all_metrics():
        """Métriques de tous les agents (Tâche 004 §3)."""
        agents = collector.get_all_agents_metrics()
        return {
            "agents": agents,
            "count": len(agents),
            "timestamp": time.time()
        }

    @router.get("/metrics/{agent_id}")
    def get_agent_metrics(agent_id: str):
        """Métriques d'un agent spécifique (Tâche 004 §1)."""
        metrics = collector.get_metrics(agent_id)
        if not metrics:
            raise HTTPException(status_code=404, detail=f"No metrics for agent {agent_id}")
        return metrics

    @router.get("/metrics/{agent_id}/latency")
    def get_agent_latency(agent_id: str, limit: int = 50):
        """Historique de latence d'un agent (Tâche 004 §3)."""
        history = collector.get_latency_history(agent_id, limit=limit)
        return {
            "agent_id": agent_id,
            "history": history,
            "count": len(history)
        }

    @router.get("/alerts")
    def get_alerts():
        """Alertes actives (Tâche 004 §2)."""
        alerts = alert_mgr.get_active_alerts()
        return {
            "alerts": alerts,
            "count": len(alerts),
            "timestamp": time.time()
        }

    @router.post("/alerts/{alert_id}/ack")
    def acknowledge_alert(alert_id: str):
        """Acquitter une alerte."""
        success = alert_mgr.acknowledge_alert(alert_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
        return {"acknowledged": True, "alert_id": alert_id}

    @router.get("/summary")
    def get_summary():
        """
        Résumé agrégé du monitoring (Tâche 004 §3).

        Returns:
            dict: score moyen, cycles complétés, messages traités/h, agents par statut
        """
        all_metrics = collector.get_all_agents_metrics()
        global_metrics = collector.get_global_metrics()
        active_alerts = alert_mgr.get_active_alerts()

        # Calculer agrégats
        total_agents = len(all_metrics)
        total_cycles = sum(int(m.get("cycles_completed", 0)) for m in all_metrics.values())
        total_tasks = int(global_metrics.get("total_tasks", 0))
        total_errors = int(global_metrics.get("total_errors", 0))

        # Score moyen
        scores = [float(m["avg_score"]) for m in all_metrics.values() if "avg_score" in m]
        avg_score = round(sum(scores) / len(scores), 1) if scores else None

        # Latence moyenne globale
        latencies = [float(m["avg_latency"]) for m in all_metrics.values() if "avg_latency" in m]
        avg_latency = round(sum(latencies) / len(latencies), 3) if latencies else None

        # Messages/heure approximatif
        messages_hour = sum(int(m.get("messages_this_hour", 0)) for m in all_metrics.values())

        # Compter alertes par niveau
        alerts_by_level = {}
        for alert in active_alerts:
            level = alert.get("level", "unknown")
            alerts_by_level[level] = alerts_by_level.get(level, 0) + 1

        return {
            "agents_monitored": total_agents,
            "total_cycles_completed": total_cycles,
            "total_tasks_completed": total_tasks,
            "total_errors": total_errors,
            "avg_score": avg_score,
            "avg_latency_seconds": avg_latency,
            "messages_per_hour": messages_hour,
            "active_alerts": len(active_alerts),
            "alerts_by_level": alerts_by_level,
            "timestamp": time.time()
        }

    @router.post("/check")
    def run_check():
        """Lance un check de tous les agents maintenant."""
        alerts = alert_mgr.check_all_agents()
        return {
            "alerts_detected": len(alerts),
            "alerts": alerts,
            "timestamp": time.time()
        }

    return router
