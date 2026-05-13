"""
alert_manager.py — Détection et gestion des alertes agents
Tâche 004 — Alertes automatiques : agent bloqué > 2 cycles, stale, erreurs

Alertes stockées dans :
  - Hash {prefix}:alerts:{alert_id} : détail alerte
  - Set {prefix}:alerts:active : IDs alertes actives
  - Stream {prefix}:alerts:stream : historique (CT-006 format)

CT-004 : Préfixe configurable, isolation tests
"""

import time
import json
import os

DEFAULT_PREFIX = os.environ.get("MA_PREFIX", "ma")

# Seuils configurables (R-TIMING: pas de valeurs hardcodées)
DEFAULT_STALE_THRESHOLD = 120      # 2 minutes sans heartbeat → stale
DEFAULT_STUCK_CYCLES = 2           # > 2 cycles sans progression → stuck
DEFAULT_ERROR_BURST_THRESHOLD = 5  # 5 erreurs en 5 min → alert
DEFAULT_ERROR_BURST_WINDOW = 300   # 5 minutes


class AlertLevel:
    """Niveaux d'alerte."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType:
    """Types d'alerte (Tâche 004)."""
    AGENT_STALE = "agent_stale"
    AGENT_STUCK = "agent_stuck"
    ERROR_BURST = "error_burst"
    AGENT_DEAD = "agent_dead"
    QUEUE_OVERFLOW = "queue_overflow"


class AlertManager:
    """
    Gère la détection et publication des alertes agents.

    Tâche 004 §2 : Alertes automatiques si un agent est bloqué > 2 cycles.

    Usage:
        manager = AlertManager(redis_client)
        alerts = manager.check_all_agents()
        active = manager.get_active_alerts()
        manager.acknowledge_alert(alert_id)
    """

    def __init__(self, redis_client, prefix=None,
                 stale_threshold=None, stuck_cycles=None,
                 error_burst_threshold=None, error_burst_window=None):
        """
        Args:
            redis_client: Instance redis.Redis connectée
            prefix: Préfixe Redis
            stale_threshold: Secondes sans heartbeat avant alerte stale
            stuck_cycles: Nombre de cycles sans progrès avant alerte stuck
            error_burst_threshold: Nombre d'erreurs avant alerte burst
            error_burst_window: Fenêtre en secondes pour le burst
        """
        self.redis = redis_client
        self.prefix = prefix or DEFAULT_PREFIX
        self.stale_threshold = stale_threshold or DEFAULT_STALE_THRESHOLD
        self.stuck_cycles = stuck_cycles or DEFAULT_STUCK_CYCLES
        self.error_burst_threshold = error_burst_threshold or DEFAULT_ERROR_BURST_THRESHOLD
        self.error_burst_window = error_burst_window or DEFAULT_ERROR_BURST_WINDOW

    def _alerts_key(self, alert_id):
        """Clé Redis pour une alerte."""
        return f"{self.prefix}:alerts:{alert_id}"

    def _active_set_key(self):
        """Clé Redis pour les alertes actives."""
        return f"{self.prefix}:alerts:active"

    def _stream_key(self):
        """Clé Redis pour le stream d'alertes."""
        return f"{self.prefix}:alerts:stream"

    def _agent_hash_key(self, agent_id):
        """Clé Redis du hash agent (convention existante)."""
        return f"{self.prefix}:agent:{agent_id}"

    def _metrics_key(self, agent_id):
        """Clé Redis des métriques agent."""
        return f"{self.prefix}:metrics:{agent_id}"

    def check_agent_stale(self, agent_id):
        """
        Vérifie si un agent est stale (pas de heartbeat récent).

        Args:
            agent_id: ID de l'agent

        Returns:
            dict or None: Alerte si stale, None sinon

        Tâche 004 : dashboard état agent (alive/dead/idle)
        """
        agent_data = self.redis.hgetall(self._agent_hash_key(agent_id))
        if not agent_data:
            return None

        last_seen = agent_data.get("last_seen")
        if not last_seen:
            return None

        age = time.time() - float(last_seen)
        if age > self.stale_threshold:
            level = AlertLevel.CRITICAL if age > self.stale_threshold * 3 else AlertLevel.WARNING
            return self._create_alert(
                agent_id=agent_id,
                alert_type=AlertType.AGENT_STALE,
                level=level,
                message=f"Agent {agent_id} stale depuis {int(age)}s (seuil: {self.stale_threshold}s)",
                details={"age_seconds": int(age), "last_seen": float(last_seen)}
            )
        return None

    def check_agent_stuck(self, agent_id):
        """
        Vérifie si un agent est bloqué (pas de progression depuis N cycles).

        Args:
            agent_id: ID de l'agent

        Returns:
            dict or None: Alerte si stuck, None sinon

        Tâche 004 §2 : agent bloqué > 2 cycles
        """
        metrics = self.redis.hgetall(self._metrics_key(agent_id))
        if not metrics:
            return None

        last_cycle_time = metrics.get("last_cycle_time")
        cycles_completed = metrics.get("cycles_completed", "0")

        if not last_cycle_time:
            return None

        # Estimation durée cycle basée sur latence moyenne
        avg_latency = float(metrics.get("avg_latency", "60"))
        expected_cycle_time = max(avg_latency * 10, 300)  # Au moins 5 min par cycle

        time_since_last = time.time() - float(last_cycle_time)
        cycles_elapsed = time_since_last / expected_cycle_time if expected_cycle_time > 0 else 0

        if cycles_elapsed > self.stuck_cycles:
            return self._create_alert(
                agent_id=agent_id,
                alert_type=AlertType.AGENT_STUCK,
                level=AlertLevel.WARNING,
                message=f"Agent {agent_id} bloqué: ~{cycles_elapsed:.1f} cycles sans progrès (seuil: {self.stuck_cycles})",
                details={
                    "cycles_elapsed": round(cycles_elapsed, 1),
                    "cycles_completed": int(cycles_completed),
                    "time_since_last_cycle": int(time_since_last)
                }
            )
        return None

    def check_error_burst(self, agent_id):
        """
        Vérifie si un agent a un burst d'erreurs récent.

        Args:
            agent_id: ID de l'agent

        Returns:
            dict or None: Alerte si burst, None sinon
        """
        metrics = self.redis.hgetall(self._metrics_key(agent_id))
        if not metrics:
            return None

        errors_total = int(metrics.get("errors_total", "0"))
        last_error_time = metrics.get("last_error_time")

        if errors_total >= self.error_burst_threshold and last_error_time:
            time_since = time.time() - float(last_error_time)
            if time_since < self.error_burst_window:
                return self._create_alert(
                    agent_id=agent_id,
                    alert_type=AlertType.ERROR_BURST,
                    level=AlertLevel.CRITICAL,
                    message=f"Agent {agent_id}: {errors_total} erreurs (dernière il y a {int(time_since)}s)",
                    details={
                        "errors_total": errors_total,
                        "last_error_type": metrics.get("last_error_type", "unknown"),
                        "time_since_last": int(time_since)
                    }
                )
        return None

    def check_all_agents(self):
        """
        Vérifie tous les agents enregistrés et retourne les alertes.

        Returns:
            list[dict]: Liste des alertes détectées

        Tâche 004 : alertes automatiques
        """
        alerts = []
        checked_agents = set()

        # Vérifier via les hashes agents (convention existante)
        pattern = f"{self.prefix}:agent:*"
        for key in self.redis.scan_iter(match=pattern):
            parts = key.split(':')
            if len(parts) == 3:  # {prefix}:agent:{id}
                agent_id = parts[2]
                if agent_id in checked_agents:
                    continue
                checked_agents.add(agent_id)

                stale = self.check_agent_stale(agent_id)
                if stale:
                    alerts.append(stale)

                stuck = self.check_agent_stuck(agent_id)
                if stuck:
                    alerts.append(stuck)

                burst = self.check_error_burst(agent_id)
                if burst:
                    alerts.append(burst)

        return alerts

    def _create_alert(self, agent_id, alert_type, level, message, details=None):
        """
        Crée et publie une alerte.

        Returns:
            dict: L'alerte créée
        """
        now = time.time()
        alert_id = f"{agent_id}:{alert_type}:{int(now)}"

        alert = {
            "id": alert_id,
            "agent_id": agent_id,
            "type": alert_type,
            "level": level,
            "message": message,
            "details": details or {},
            "timestamp": now,
            "acknowledged": False
        }

        # Stocker l'alerte
        self.redis.hset(self._alerts_key(alert_id), mapping={
            "agent_id": agent_id,
            "type": alert_type,
            "level": level,
            "message": message,
            "details": json.dumps(details or {}),
            "timestamp": now,
            "acknowledged": "false"
        })

        # Ajouter aux alertes actives
        self.redis.sadd(self._active_set_key(), alert_id)

        # Publier dans le stream (CT-006: format standard)
        self.redis.xadd(self._stream_key(), {
            "from": "alert_manager",
            "type": f"alert:{level}",
            "payload": json.dumps(alert),
            "timestamp": str(int(now))
        })

        return alert

    def get_active_alerts(self):
        """
        Récupère toutes les alertes actives.

        Returns:
            list[dict]: Alertes actives triées par timestamp

        Tâche 004 : dashboard alertes
        """
        alert_ids = self.redis.smembers(self._active_set_key())
        alerts = []
        for alert_id in alert_ids:
            raw = self.redis.hgetall(self._alerts_key(alert_id))
            if raw:
                alert = dict(raw)
                alert["id"] = alert_id
                if "details" in alert:
                    try:
                        alert["details"] = json.loads(alert["details"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                if "timestamp" in alert:
                    alert["timestamp"] = float(alert["timestamp"])
                alerts.append(alert)

        return sorted(alerts, key=lambda a: a.get("timestamp", 0), reverse=True)

    def acknowledge_alert(self, alert_id):
        """
        Acquitte une alerte (la retire des actives).

        Args:
            alert_id: ID de l'alerte

        Returns:
            bool: True si l'alerte existait et a été acquittée
        """
        removed = self.redis.srem(self._active_set_key(), alert_id)
        if removed:
            self.redis.hset(self._alerts_key(alert_id), "acknowledged", "true")
        return bool(removed)

    def clear_all_alerts(self):
        """Supprime toutes les alertes actives."""
        alert_ids = self.redis.smembers(self._active_set_key())
        for alert_id in alert_ids:
            self.redis.delete(self._alerts_key(alert_id))
        self.redis.delete(self._active_set_key())
