"""
metrics_collector.py — Collecte et stockage des métriques agents
EF-003 (heartbeats enrichis), EF-008 (extraction monitoring)
Tâche 004 — Métriques : latence, erreurs, throughput, historique

Stockage Redis :
  - Hash {prefix}:metrics:{agent_id} : métriques courantes
  - List {prefix}:metrics:{agent_id}:latency_log : dernières N latences
  - Hash {prefix}:metrics:global : agrégats globaux

CT-002 : Préfixe mi: pour streams monitoring
CT-004 : Préfixe configurable, isolation tests
CT-009 : XTRIM MAXLEN ~1000 sur streams heartbeat
"""

import time
import json
import os

# Configurable prefix (CT-002: mi: pour monitoring, CT-004: test isolation)
DEFAULT_PREFIX = os.environ.get("MA_PREFIX", "mi")

# Timing constants (R-TIMING)
LATENCY_HISTORY_MAX = 100
THROUGHPUT_WINDOW = 3600  # 1 hour


class MetricsCollector:
    """Collecte les métriques de performance des agents (EF-003, EF-008, Tâche 004 §3).

    Métriques trackées : latence, erreurs, throughput, cycles, heartbeats.
    CT-002 préfixe mi:, CT-004 isolation, CT-009 XTRIM.
    """

    def __init__(self, redis_client, prefix=None):
        """Args: redis_client (redis.Redis), prefix (str, défaut mi: CT-002)."""
        self.redis = redis_client
        self.prefix = prefix or DEFAULT_PREFIX

    def _metrics_key(self, agent_id):
        """Clé Redis pour les métriques d'un agent."""
        return f"{self.prefix}:metrics:{agent_id}"

    def _latency_key(self, agent_id):
        """Clé Redis pour l'historique de latence d'un agent."""
        return f"{self.prefix}:metrics:{agent_id}:latency_log"

    def _global_key(self):
        """Clé Redis pour les métriques globales."""
        return f"{self.prefix}:metrics:global"

    def record_task_start(self, agent_id, task_id=None):
        """
        Enregistre le début d'une tâche pour mesurer la latence.

        Args:
            agent_id: ID de l'agent (ex: "345")
            task_id: Identifiant optionnel de la tâche

        Tâche 004 : latence par tâche (prompt → réponse)
        """
        key = self._metrics_key(agent_id)
        now = time.time()
        self.redis.hset(key, "last_task_start", now)
        if task_id:
            self.redis.hset(key, "current_task_id", task_id)

    def record_task_end(self, agent_id, task_id=None, success=True):
        """
        Enregistre la fin d'une tâche, calcule la latence.

        Args:
            agent_id: ID de l'agent
            task_id: Identifiant optionnel de la tâche
            success: True si la tâche a réussi

        Returns:
            float: Latence en secondes, ou None si pas de start enregistré

        Tâche 004 : latence par tâche, throughput
        """
        key = self._metrics_key(agent_id)
        now = time.time()

        start_time = self.redis.hget(key, "last_task_start")
        latency = None
        if start_time:
            latency = now - float(start_time)

            # Stocker la latence dans l'historique (FIFO, max N)
            latency_key = self._latency_key(agent_id)
            entry = json.dumps({
                "latency": round(latency, 3),
                "timestamp": now,
                "task_id": task_id,
                "success": success
            })
            self.redis.rpush(latency_key, entry)
            self.redis.ltrim(latency_key, -LATENCY_HISTORY_MAX, -1)

            # Mettre à jour la latence moyenne
            self._update_avg_latency(agent_id, latency)

        # Incrémenter compteurs
        self.redis.hincrby(key, "tasks_total", 1)
        if success:
            self.redis.hincrby(key, "tasks_success", 1)
        else:
            self.redis.hincrby(key, "tasks_failed", 1)

        # Throughput : incrémenter compteur horaire
        self.redis.hincrby(key, "messages_this_hour", 1)
        self.redis.hset(key, "last_task_end", now)
        self.redis.hdel(key, "last_task_start", "current_task_id")

        # Métriques globales
        self.redis.hincrby(self._global_key(), "total_tasks", 1)

        return latency

    def _update_avg_latency(self, agent_id, latency):
        """Met à jour la latence moyenne glissante."""
        key = self._metrics_key(agent_id)
        raw_avg = self.redis.hget(key, "avg_latency")
        raw_count = self.redis.hget(key, "latency_count")

        avg = float(raw_avg) if raw_avg else 0.0
        count = int(raw_count) if raw_count else 0

        new_count = count + 1
        new_avg = avg + (latency - avg) / new_count

        self.redis.hset(key, mapping={
            "avg_latency": round(new_avg, 3),
            "latency_count": new_count,
            "last_latency": round(latency, 3)
        })

    def record_error(self, agent_id, error_type, message=""):
        """
        Enregistre une erreur pour un agent.

        Args:
            agent_id: ID de l'agent
            error_type: Type d'erreur (ex: "TimeoutError", "ConnectionError")
            message: Message d'erreur optionnel

        Tâche 004 : compteur d'erreurs et types
        """
        key = self._metrics_key(agent_id)
        now = time.time()

        self.redis.hincrby(key, "errors_total", 1)
        self.redis.hincrby(key, f"errors:{error_type}", 1)
        self.redis.hset(key, "last_error_time", now)
        self.redis.hset(key, "last_error_type", error_type)
        if message:
            self.redis.hset(key, "last_error_message", message[:200])

        # Globales
        self.redis.hincrby(self._global_key(), "total_errors", 1)

    def record_cycle_complete(self, agent_id, cycle_number, score=None):
        """
        Enregistre la complétion d'un cycle avec score optionnel.

        Args:
            agent_id: ID de l'agent
            cycle_number: Numéro du cycle
            score: Score du cycle (0-100), optionnel

        Tâche 004 : cycles complétés, score moyen
        """
        key = self._metrics_key(agent_id)

        self.redis.hincrby(key, "cycles_completed", 1)
        self.redis.hset(key, "last_cycle", cycle_number)
        self.redis.hset(key, "last_cycle_time", time.time())

        if score is not None:
            raw_avg = self.redis.hget(key, "avg_score")
            raw_count = self.redis.hget(key, "score_count")

            avg = float(raw_avg) if raw_avg else 0.0
            count = int(raw_count) if raw_count else 0

            new_count = count + 1
            new_avg = avg + (score - avg) / new_count

            self.redis.hset(key, mapping={
                "avg_score": round(new_avg, 1),
                "score_count": new_count,
                "last_score": score
            })

    def record_message(self, agent_id, direction="inbound"):
        """
        Enregistre un message traité (pour throughput).

        Args:
            agent_id: ID de l'agent
            direction: "inbound" ou "outbound"

        Tâche 004 : messages traités/h
        """
        key = self._metrics_key(agent_id)
        self.redis.hincrby(key, f"messages_{direction}", 1)
        self.redis.hset(key, "last_message_time", time.time())
        self.redis.hincrby(self._global_key(), "total_messages", 1)

    def get_metrics(self, agent_id):
        """
        Récupère toutes les métriques d'un agent.

        Args:
            agent_id: ID de l'agent

        Returns:
            dict: Métriques de l'agent, ou dict vide si aucune donnée

        Tâche 004 : dashboard temps réel
        """
        key = self._metrics_key(agent_id)
        raw = self.redis.hgetall(key)
        if not raw:
            return {}

        metrics = {}
        for k, v in raw.items():
            try:
                if '.' in v:
                    metrics[k] = float(v)
                else:
                    metrics[k] = int(v)
            except (ValueError, TypeError):
                metrics[k] = v

        metrics["agent_id"] = agent_id
        return metrics

    def get_latency_history(self, agent_id, limit=None):
        """
        Récupère l'historique de latence d'un agent.

        Args:
            agent_id: ID de l'agent
            limit: Nombre max d'entrées (défaut: toutes)

        Returns:
            list[dict]: Historique de latence

        Tâche 004 : historique (tendance)
        """
        key = self._latency_key(agent_id)
        if limit:
            entries = self.redis.lrange(key, -limit, -1)
        else:
            entries = self.redis.lrange(key, 0, -1)
        return [json.loads(e) for e in entries]

    def get_global_metrics(self):
        """
        Récupère les métriques globales agrégées.

        Returns:
            dict: Métriques globales

        Tâche 004 : métriques agrégées
        """
        raw = self.redis.hgetall(self._global_key())
        metrics = {}
        for k, v in raw.items():
            try:
                metrics[k] = int(v)
            except (ValueError, TypeError):
                metrics[k] = v
        return metrics

    def get_all_agents_metrics(self):
        """
        Récupère les métriques de tous les agents monitorés.

        Returns:
            dict[str, dict]: Métriques par agent_id

        Tâche 004 : dashboard temps réel
        """
        pattern = f"{self.prefix}:metrics:*"
        all_metrics = {}
        for key in self.redis.scan_iter(match=pattern):
            # Filtrer les sous-clés (latency_log, etc.)
            parts = key.split(':')
            if len(parts) == 3:  # {prefix}:metrics:{agent_id}
                agent_id = parts[2]
                if agent_id != "global":
                    all_metrics[agent_id] = self.get_metrics(agent_id)
        return all_metrics

    def record_heartbeat(self, agent_id, heartbeat_data):
        """Enregistre un heartbeat enrichi (EF-003, CA-004).

        Args:
            agent_id: ID de l'agent
            heartbeat_data: dict avec les 7 champs EF-003
        """
        key = self._metrics_key(agent_id)
        self.redis.hset(key, "last_heartbeat_ts", heartbeat_data.get("timestamp", time.time()))
        if "memory_mb" in heartbeat_data:
            self.redis.hset(key, "last_memory_mb", heartbeat_data["memory_mb"])
        if "cpu_percent" in heartbeat_data:
            self.redis.hset(key, "last_cpu_percent", heartbeat_data["cpu_percent"])
        self.redis.hincrby(key, "heartbeats_total", 1)

    def reset_agent_metrics(self, agent_id):
        """Remet à zéro les métriques d'un agent."""
        self.redis.delete(self._metrics_key(agent_id))
        self.redis.delete(self._latency_key(agent_id))
