#!/usr/bin/env python3
"""
wal.py — V3/C2 : write-ahead log des événements d'orchestration.

Stream Redis {MA_PREFIX}:wal — audit + reprise. Le state_file du
workflow_engine RESTE la source de vérité pour la reprise des workflows ;
le WAL sert à l'observabilité (bench C0, détection de stall, post-mortem)
et au diagnostic de crash du bridge.

Événements émis (champ event) :
  task_assigned      — le bridge prend une tâche (agent.py)
  verify_green       — verify vert (agent.py)
  verify_red         — verify rouge, retry (agent.py)
  verify_retry       — re-dispatch après rouge (agent.py)
  verify_escalation  — budget épuisé / hacking / deadline (agent.py)
  api_error_retry    — erreur API, re-queue (agent.py)
  nudge              — relance watchdog sur agent silencieux (healthcheck.py)
  escalation         — alerte critique watchdog (healthcheck.py)

Toutes les écritures sont best-effort côté appelant : un émetteur ne doit
JAMAIS crasher parce que Redis est indisponible (wrapper try/except).
"""
import os
import time

WAL_MAXLEN = int(os.environ.get("WAL_MAXLEN", 100000))
_BATCH = 1000
_FIELD_MAX = 500


def stream(prefix):
    return f"{prefix}:wal"


def emit(redis_cli, prefix, event, agent_id, task_id="-", **fields):
    """Ajoute un événement au WAL. Retourne l'ID du message."""
    entry = {
        "event": str(event),
        "agent_id": str(agent_id),
        "task_id": str(task_id or "-"),
        "ts": int(time.time()),
    }
    for key, value in fields.items():
        entry[key] = str(value)[:_FIELD_MAX]
    return redis_cli.xadd(stream(prefix), entry,
                          maxlen=WAL_MAXLEN, approximate=True)


def last_event(redis_cli, prefix, agent_id, events=None):
    """Dernier événement WAL de l'agent (optionnellement filtré par types).

    Retourne (msg_id, data) ou None. Parcours XREVRANGE paginé (l'ID
    exclusif '(' requiert Redis >= 6.2).
    """
    agent_id = str(agent_id)
    last_id = "+"
    while True:
        batch = redis_cli.xrevrange(stream(prefix), max=last_id, min="-",
                                    count=_BATCH)
        if not batch:
            return None
        for msg_id, data in batch:
            if data.get("agent_id") != agent_id:
                continue
            if events and data.get("event") not in events:
                continue
            return (msg_id, data)
        if len(batch) < _BATCH:
            return None
        last_id = "(" + batch[-1][0]


def open_task(redis_cli, prefix, agent_id):
    """task_id assigné à l'agent sans clôture (verify_green/verify_escalation).

    Parcours chronologique paginé du WAL. Retourne le task_id ouvert ou None.
    Diagnostic post-crash : le consumer group redélivre de toute façon (A4),
    ce helper sert au log de reprise, pas à la re-exécution.
    """
    agent_id = str(agent_id)
    current = None
    last_id = "-"
    while True:
        batch = redis_cli.xrange(stream(prefix), min=last_id, max="+",
                                 count=_BATCH)
        if not batch:
            return current
        for _msg_id, data in batch:
            if data.get("agent_id") != agent_id:
                continue
            event = data.get("event")
            if event == "task_assigned":
                current = data.get("task_id") or None
                if current == "-":
                    current = None
            elif event in ("verify_green", "verify_escalation"):
                current = None
        if len(batch) < _BATCH:
            return current
        last_id = "(" + batch[-1][0]
