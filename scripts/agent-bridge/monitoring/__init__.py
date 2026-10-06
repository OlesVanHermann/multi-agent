"""
monitoring — Système de monitoring agents pour le Multi-Agent Framework
EF-004 (alerting), EF-008 (extraction monitoring)
Tâche 004 : Dashboard temps réel, alertes, métriques de performance

Modules :
  - metrics_collector : Collecte latence, erreurs, throughput (EF-003, EF-008)
  - alerting : Détection agents bloqués/stale, alertes configurables (EF-004)
  - dashboard_api : Endpoints FastAPI pour les données de monitoring (EF-008)
"""

from .metrics_collector import MetricsCollector
from .alerting import AlertManager

__all__ = ['MetricsCollector', 'AlertManager']
