"""
alerting.py — Détection et gestion des alertes agents
EF-004 : Système d'alerting structuré — CT-006 (<200L), CT-009 (XTRIM)
CT-002 : Préfixe mi:, format from/type/payload/timestamp
Ref spec 342 : CA-005 (alertes logguées), Tâche 004 §2 (agents bloqués >2 cycles)
"""

import time
import json
import os

DEFAULT_PREFIX = os.environ.get("MA_PREFIX", "mi")

# Seuils configurables (Tâche 004 §2, R-TIMING)
STALE_THRESHOLD = 120       # 2 min sans heartbeat → stale
STUCK_CYCLES = 2            # >2 cycles sans progrès → stuck
ERROR_BURST_THRESHOLD = 5   # 5 erreurs en fenêtre → burst
ERROR_BURST_WINDOW = 300    # fenêtre 5 min
STREAM_MAXLEN = 1000        # CT-009: XTRIM borne streams


class AlertManager:
    """Détection agents stale/stuck/burst, publication alertes (EF-004, CT-006).

    Seuils configurables en constructeur. Publication stream CT-002 + CT-009.
    Heuristique stuck: expected_cycle_time = max(avg_latency*10, 300) — P4 documenté.
    """

    def __init__(self, redis_client, prefix=None,
                 stale_threshold=None, stuck_cycles=None,
                 error_burst_threshold=None, error_burst_window=None):
        self.redis = redis_client
        self.prefix = prefix or DEFAULT_PREFIX
        self.stale_threshold = stale_threshold or STALE_THRESHOLD
        self.stuck_cycles = stuck_cycles or STUCK_CYCLES
        self.error_burst_threshold = error_burst_threshold or ERROR_BURST_THRESHOLD
        self.error_burst_window = error_burst_window or ERROR_BURST_WINDOW

    def _stream_key(self):
        return f"{self.prefix}:alerts:stream"

    def _active_set_key(self):
        return f"{self.prefix}:alerts:active"

    def _alerts_key(self, alert_id):
        return f"{self.prefix}:alerts:{alert_id}"

    def check_agent_stale(self, agent_id):
        """Vérifie heartbeat récent — EF-004, CA-004."""
        data = self.redis.hgetall(f"{self.prefix}:agent:{agent_id}")
        if not data or "last_seen" not in data:
            return None
        age = time.time() - float(data["last_seen"])
        if age > self.stale_threshold:
            level = "critical" if age > self.stale_threshold * 3 else "warning"
            return self._create_alert(agent_id, "agent_stale", level,
                f"Agent {agent_id} stale {int(age)}s (seuil: {self.stale_threshold}s)",
                {"age_seconds": int(age), "last_seen": float(data["last_seen"])})
        return None

    def check_agent_stuck(self, agent_id):
        """Vérifie progression cycles — EF-004, Tâche 004 §2 (>2 cycles)."""
        metrics = self.redis.hgetall(f"{self.prefix}:metrics:{agent_id}")
        if not metrics or "last_cycle_time" not in metrics:
            return None
        avg_lat = float(metrics.get("avg_latency", "60"))
        expected = max(avg_lat * 10, 300)
        elapsed = time.time() - float(metrics["last_cycle_time"])
        cycles = elapsed / expected if expected > 0 else 0
        if cycles > self.stuck_cycles:
            return self._create_alert(agent_id, "agent_stuck", "warning",
                f"Agent {agent_id} bloqué ~{cycles:.1f} cycles",
                {"cycles_elapsed": round(cycles, 1),
                 "cycles_completed": int(metrics.get("cycles_completed", "0")),
                 "time_since_last_cycle": int(elapsed)})
        return None

    def check_error_burst(self, agent_id):
        """Vérifie burst d'erreurs récent — EF-004."""
        metrics = self.redis.hgetall(f"{self.prefix}:metrics:{agent_id}")
        if not metrics:
            return None
        errors = int(metrics.get("errors_total", "0"))
        last_err = metrics.get("last_error_time")
        if errors >= self.error_burst_threshold and last_err:
            if time.time() - float(last_err) < self.error_burst_window:
                return self._create_alert(agent_id, "error_burst", "critical",
                    f"Agent {agent_id}: {errors} erreurs",
                    {"errors_total": errors,
                     "last_error_type": metrics.get("last_error_type", "unknown")})
        return None

    def check_all_agents(self):
        """Scanne tous les agents, retourne alertes — EF-004, Tâche 004."""
        alerts, seen = [], set()
        for key in self.redis.scan_iter(match=f"{self.prefix}:agent:*"):
            parts = key.split(':')
            if len(parts) == 3:
                aid = parts[2]
                if aid not in seen:
                    seen.add(aid)
                    for fn in (self.check_agent_stale, self.check_agent_stuck,
                               self.check_error_burst):
                        alert = fn(aid)
                        if alert:
                            alerts.append(alert)
        return alerts

    def _create_alert(self, agent_id, alert_type, level, message, details=None):
        """Crée, stocke et publie alerte — CT-002 format, CT-009 XTRIM (R-XTRIM)."""
        now = time.time()
        alert_id = f"{agent_id}:{alert_type}:{int(now)}"
        alert = {"id": alert_id, "agent_id": agent_id, "type": alert_type,
                 "level": level, "message": message,
                 "details": details or {}, "timestamp": now, "acknowledged": False}
        self.redis.hset(self._alerts_key(alert_id), mapping={
            "agent_id": agent_id, "type": alert_type, "level": level,
            "message": message, "details": json.dumps(details or {}),
            "timestamp": now, "acknowledged": "false"})
        self.redis.sadd(self._active_set_key(), alert_id)
        self.redis.xadd(self._stream_key(), {
            "from": "alert_manager", "type": f"alert:{level}",
            "payload": json.dumps(alert), "timestamp": str(int(now))
        }, maxlen=STREAM_MAXLEN, approximate=True)
        return alert

    def get_active_alerts(self):
        """Récupère alertes actives triées par timestamp — EF-004."""
        alerts = []
        for alert_id in self.redis.smembers(self._active_set_key()):
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
        """Acquitte une alerte — EF-004."""
        removed = self.redis.srem(self._active_set_key(), alert_id)
        if removed:
            self.redis.hset(self._alerts_key(alert_id), "acknowledged", "true")
        return bool(removed)

    def clear_all_alerts(self):
        """Supprime toutes les alertes actives."""
        for aid in self.redis.smembers(self._active_set_key()):
            self.redis.delete(self._alerts_key(aid))
        self.redis.delete(self._active_set_key())
