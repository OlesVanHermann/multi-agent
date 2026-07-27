#!/usr/bin/env python3
"""Obligations durables créées par DISPATCH et closes par terminal corrélé."""

import argparse
import json
import os
import re
import time
from pathlib import Path


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _component(value):
    value = _SAFE.sub("_", str(value or "")).strip("._")
    return value or "unattributed"


def obligation_dir(base_dir, task_id, cycle):
    return (
        Path(base_dir)
        / "pool-requests"
        / "state"
        / _component(task_id)
        / _component(cycle)
        / "obligations"
    )


def obligation_path(base_dir, task_id, cycle, agent_id):
    return obligation_dir(base_dir, task_id, cycle) / f"{_component(agent_id)}.json"


def create(base_dir, agent_id, message, msg_id, now=None):
    """Crée atomiquement l'obligation d'un DISPATCH, sinon retourne None."""
    if message.get("event") != "DISPATCH" or not message.get("expected_event"):
        return None
    now = int(now if now is not None else time.time())
    path = obligation_path(
        base_dir, message.get("task_id"), message.get("cycle"), agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requester": message.get("requester", ""),
        "owner": agent_id,
        "expected_event": message.get("expected_event", ""),
        "correlation_id": message.get("correlation_id", ""),
        "task_id": message.get("task_id", ""),
        "cycle": message.get("cycle", ""),
        "received_at": now,
        "msg_id": str(msg_id),
        "status": "OPEN",
    }
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
    return path


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return None


def iter_open(base_dir):
    root = Path(base_dir) / "pool-requests" / "state"
    if not root.is_dir():
        return
    for path in sorted(root.glob("*/*/obligations/*.json")):
        data = load(path)
        if data and data.get("status", "OPEN") == "OPEN":
            yield path, data


def update(path, **fields):
    data = load(path)
    if not data:
        return False
    data.update(fields)
    temporary = Path(path).with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
    return True


def close(base_dir, task_id, cycle, agent_id, correlation_id, event, now=None):
    """Archive une obligation uniquement si corrélation et terminal concordent."""
    path = obligation_path(base_dir, task_id, cycle, agent_id)
    data = load(path)
    if not data:
        return None
    if data.get("correlation_id") != correlation_id:
        return None
    if data.get("expected_event") != event:
        return None
    now = int(now if now is not None else time.time())
    data.update({"status": "DELIVERED", "delivered_at": now, "event": event})
    update(path, **data)
    archive = path.parent.parent / "obligations-closed"
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / f"{path.stem}-{now}.json"
    path.replace(destination)
    return destination


def reconcile(redis_client, base_dir):
    """Ferme les obligations dont le terminal structuré existe déjà."""
    entries = redis_client.xrange("completion")
    terminals = {}
    for _msg_id, data in entries:
        key = (
            data.get("correlation_id", ""),
            data.get("cycle", ""),
            data.get("from", ""),
            data.get("event", ""),
        )
        terminals[key] = data
    closed = []
    for path, obligation in list(iter_open(base_dir) or []):
        key = (
            obligation.get("correlation_id", ""),
            obligation.get("cycle", ""),
            obligation.get("owner", ""),
            obligation.get("expected_event", ""),
        )
        if key in terminals:
            archived = close(
                base_dir,
                obligation.get("task_id"),
                obligation.get("cycle"),
                obligation.get("owner"),
                obligation.get("correlation_id"),
                obligation.get("expected_event"),
            )
            if archived:
                closed.append(archived)
    return closed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("close",))
    parser.add_argument("--base", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--correlation", required=True)
    parser.add_argument("--event", required=True)
    args = parser.parse_args()
    archived = close(
        args.base, args.task, args.cycle, args.agent, args.correlation, args.event)
    print(f"closed:{archived}" if archived else "no-match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
