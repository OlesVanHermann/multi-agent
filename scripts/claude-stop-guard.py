#!/usr/bin/env python3
"""Claude Stop hook: refuse un idle inter-agent sans événement corrélé.

Le hook est volontairement fail-open pour les tours conversationnels, les
commandes CLI, une corrélation absente et une indisponibilité Redis. Le bridge
reste le second filet et publie PROTOCOL_ERROR après une relance bornée.
"""

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


def event_exists(client, agent_id, requester, correlation_id):
    for _, fields in client.xrevrange("completion", count=200):
        if (fields.get("correlation_id") == correlation_id
                and fields.get("from") == agent_id):
            return True
    for _, fields in client.xrevrange(
            f"agent:{requester}:inbox", count=200):
        if (fields.get("correlation_id") == correlation_id
                and fields.get("from_agent") == agent_id
                and fields.get("event") not in ("", "DISPATCH")):
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
        if (not correlation_id or not is_valid_agent_id(requester)
                or requester == agent_id):
            return 0
        if event_exists(client, agent_id, requester, correlation_id):
            return 0
    except (redis.RedisError, OSError, ValueError):
        return 0
    print(
        "Fin de tour refusée : aucune livraison métier corrélée. "
        f"Exécute send.sh ou done.sh vers {requester} avec "
        f"TASK_ID={task_id}, CYCLE={cycle}, "
        f"CORRELATION_ID={correlation_id}.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
