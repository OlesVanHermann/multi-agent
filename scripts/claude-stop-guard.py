#!/usr/bin/env python3
"""Claude Stop hook: refuse un idle sans retour dû et rapport au Master."""

import json
import os
import subprocess
import sys
from pathlib import Path

import redis

BRIDGE_DIR = Path(__file__).resolve().parent / "agent-bridge"
sys.path.insert(0, str(BRIDGE_DIR))
from ids import is_valid_agent_id  # noqa: E402


def hook_input():
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}


def current_agent_id():
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return ""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, "#{session_name}"],
            capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    session = result.stdout.strip()
    if not session.startswith("agent-"):
        return ""
    agent_id = session.removeprefix("agent-")
    return agent_id if is_valid_agent_id(agent_id) else ""


def redis_client():
    base = Path(__file__).resolve().parents[1]
    secrets = base / "setup" / "secrets.cfg"
    password = os.environ.get("REDIS_PASSWORD", "")
    if not password and secrets.is_file():
        for line in secrets.read_text(errors="replace").splitlines():
            if line.startswith("REDIS_PASSWORD="):
                password = line.split("=", 1)[1].strip().strip("\"'")
                break
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=password or None,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def event_exists(client, agent_id, requester, correlation_id, started_at):
    for msg_id, fields in client.xrevrange("completion", count=200):
        event_at = int(fields.get("timestamp", "0") or 0)
        if (fields.get("correlation_id") == correlation_id
                and fields.get("from") == agent_id
                and event_at >= started_at):
            return True
    for msg_id, fields in client.xrevrange(
            f"agent:{requester}:inbox", count=200):
        event_at = int(fields.get("timestamp", "0") or 0)
        if (fields.get("correlation_id") == correlation_id
                and fields.get("from_agent") == agent_id
                and fields.get("event") not in ("", "DISPATCH")
                and event_at >= started_at):
            return True
    return False


def main():
    data = hook_input()
    # Claude réexécute le Stop hook après la correction demandée. Ne jamais
    # créer une boucle infinie ; le bridge prend alors le relais.
    if data.get("stop_hook_active"):
        return 0
    agent_id = current_agent_id()
    if not is_valid_agent_id(agent_id):
        return 0
    try:
        client = redis_client()
        state = client.hgetall(f"agent:{agent_id}")
        correlation_id = state.get("current_correlation", "")
        requester = state.get("current_requester", "")
        task_id = state.get("current_task_id", "")
        cycle = state.get("current_cycle", "")
        started_at = int(state.get("current_task_started_at", "0") or 0)
        report_id = state.get("last_master_report_id", "")
        consumed_report_id = state.get("last_stop_master_report_id", "")
        parts = agent_id.split("-")
        master_id = ""
        if len(parts) == 2 and len(parts[1]) == 3:
            master_id = f"{parts[0]}-1{parts[1][1:]}"

        missing = []
        if (correlation_id and is_valid_agent_id(requester)
                and requester != agent_id
                and not event_exists(
                    client, agent_id, requester, correlation_id, started_at)):
            missing.append(
                f"livraison corrélée vers {requester} "
                f"(TASK_ID={task_id}, CYCLE={cycle}, "
                f"CORRELATION_ID={correlation_id})")
        if master_id and master_id != agent_id and (
                not report_id or report_id == consumed_report_id):
            missing.append(f"MASTER_REPORT vers {master_id}")
        if not missing:
            if report_id:
                client.hset(
                    f"agent:{agent_id}", "last_stop_master_report_id", report_id)
            return 0
    except (redis.RedisError, OSError, ValueError):
        return 0
    print(
        "Fin de tour refusée : " + " et ".join(missing) + " manquant(s). "
        "Livre d'abord la réponse corrélée si elle est due, puis exécute "
        "./scripts/report-master.sh <STATUS> '<résumé factuel>'.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
