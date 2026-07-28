#!/usr/bin/env python3
"""Obligations durables créées par DISPATCH et closes par terminal corrélé."""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _component(value):
    value = _SAFE.sub("_", str(value or "")).strip("._")
    return value or "unattributed"


def _expected_set(expected_event):
    """Décompose un EXPECTED_EVENT en ensemble d'alternatives.

    Un champ atomique (`ARBITRAGE`) donne un ensemble singleton ; un champ
    composite (`ARBITRAGE|INFO_REQUIRED|BLOCKED|ERROR`) donne l'ensemble de ses
    alternatives. La comparaison de clôture teste alors l'appartenance, jamais
    l'égalité littérale.
    """
    return {token for token in str(expected_event or "").split("|") if token}


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
    if event not in _expected_set(data.get("expected_event")):
        return None
    now = int(now if now is not None else time.time())
    data.update({"status": "DELIVERED", "delivered_at": now, "event": event})
    update(path, **data)
    archive = path.parent.parent / "obligations-closed"
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / f"{path.stem}-{now}.json"
    path.replace(destination)
    return destination


def close_status(base_dir, task_id, cycle, agent_id, correlation_id, event,
                 now=None):
    """Tente la clôture et classe le résultat pour la comptabilité durable.

    Retourne ``(status, detail)`` :

    - ``("closed", chemin)`` : obligation OPEN archivée ;
    - ``("absent", "")`` : aucune obligation OPEN (rien à comptabiliser — cas
      d'un émetteur sans DISPATCH ou d'un rejeu déjà archivé, donc idempotent) ;
    - ``("corr-mismatch", corr_stockée)`` : obligation OPEN mais corrélation
      différente ;
    - ``("event-unexpected", ensemble_attendu)`` : événement hors de
      l'ensemble attendu.

    Les deux derniers sont des échecs de comptabilité que ``done.sh`` doit
    rendre visibles sans réémettre de terminal.
    """
    path = obligation_path(base_dir, task_id, cycle, agent_id)
    data = load(path)
    if not data or data.get("status") != "OPEN":
        return ("absent", "")
    if data.get("correlation_id") != correlation_id:
        return ("corr-mismatch", data.get("correlation_id", ""))
    expected = _expected_set(data.get("expected_event"))
    if event not in expected:
        return ("event-unexpected", "|".join(sorted(expected)))
    destination = close(
        base_dir, task_id, cycle, agent_id, correlation_id, event, now=now)
    if destination:
        return ("closed", str(destination))
    return ("absent", "")


def reconcile(redis_client, base_dir):
    """Ferme les obligations dont le terminal structuré existe déjà."""
    entries = redis_client.xrange("completion")
    # Un même (corrélation, cycle, émetteur) peut porter plusieurs terminaux ;
    # on collecte l'ensemble des événements réellement livrés.
    terminals = {}
    for _msg_id, data in entries:
        key = (
            data.get("task_id", ""),
            data.get("correlation_id", ""),
            data.get("cycle", ""),
            data.get("from", ""),
        )
        terminals.setdefault(key, set()).add(data.get("event", ""))
    closed = []
    for path, obligation in list(iter_open(base_dir) or []):
        key = (
            obligation.get("task_id", ""),
            obligation.get("correlation_id", ""),
            obligation.get("cycle", ""),
            obligation.get("owner", ""),
        )
        delivered = terminals.get(key, set())
        expected = _expected_set(obligation.get("expected_event"))
        # Premier attendu réellement livré, en respectant l'ordre déclaré.
        event = next(
            (token for token in str(obligation.get("expected_event") or "").split("|")
             if token and token in delivered and token in expected),
            None,
        )
        if event is None:
            continue
        archived = close(
            base_dir,
            obligation.get("task_id"),
            obligation.get("cycle"),
            obligation.get("owner"),
            obligation.get("correlation_id"),
            event,
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
    status, detail = close_status(
        args.base, args.task, args.cycle, args.agent, args.correlation,
        args.event)
    if status == "closed":
        print(f"closed:{detail}")
        return 0
    if status == "absent":
        # Rien à comptabiliser : pas d'obligation OPEN (émetteur sans DISPATCH
        # ou rejeu déjà archivé). Idempotent, aucune seconde archive.
        print("no-obligation")
        return 0
    # Échec de comptabilité : l'obligation reste OPEN alors qu'un terminal a
    # pu être livré. On l'expose par un code non nul distinct (4), sans jamais
    # réémettre de terminal.
    print(f"unreconciled:{status}:{detail}", file=sys.stderr)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
