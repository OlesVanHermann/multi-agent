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
                and str(fields.get("event", "") or "").upper()
                != "DECISION_REQUIRED"
                and str(fields.get("classification", "") or "").lower()
                != "supervision_blocking"
                and event_at >= started_at):
            return True
    return False


def master_report_for_turn(
        client, state, agent_id, master_id, current_turn_id):
    """Retourne l'ID du rapport qui prouve le tour courant.

    Le pointeur d'état v1 est atomique avec l'écriture du rapport. Le scan du
    stream couvre un état ancien/incomplet et le format legacy
    ``correlation_id=turn-<uuid>``. Sans identité de tour (bridge ancien), le
    compteur consommé/non consommé historique reste le seul signal possible.
    """
    report_id = str(state.get("last_master_report_id", "") or "")
    consumed = str(state.get("last_stop_master_report_id", "") or "")
    source_turn = str(
        state.get("last_master_report_source_turn_id", "")
        or state.get("last_master_report_turn_id", "")
        or "")

    if not current_turn_id:
        return report_id if report_id and report_id != consumed else ""
    if (report_id and report_id != consumed
            and source_turn == current_turn_id):
        return report_id

    for stream_id, fields in client.xrevrange(
            f"agent:{master_id}:reports", count=200):
        if (fields.get("from_agent") != agent_id
                or fields.get("event") != "MASTER_REPORT"):
            continue
        entry_turn = str(
            fields.get("source_turn_id", "")
            or fields.get("turn_id", "")
            or "")
        entry_report_id = str(
            fields.get("report_id", "") or stream_id or "")
        matches_v1 = entry_turn == current_turn_id
        matches_legacy = (
            fields.get("correlation_id") == f"turn-{current_turn_id}")
        if not (matches_v1 or matches_legacy):
            continue
        # Un pointeur v1 précis ne peut valider un autre rapport. Le format
        # legacy stockait le turn_id lui-même dans last_master_report_id.
        if (report_id and report_id not in {
                entry_report_id, str(stream_id), current_turn_id}):
            continue
        if entry_report_id != consumed:
            return entry_report_id
    return ""


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
        current_turn_id = str(state.get("current_turn_id", "") or "")
        # Fail-closed : un bridge non redémarré (champs d'obligation absents
        # du hash) garde la sémantique v3.2.12 au lieu de désactiver la
        # garde. Les champs explicites ("0"/"1") d'un bridge neuf font foi.
        has_obligation_fields = (
            "current_delivery_obligation" in state
            or "current_master_report_obligation" in state)
        if has_obligation_fields:
            delivery_obligation = (
                state.get("current_delivery_obligation", "") == "1")
            master_report_obligation = (
                state.get("current_master_report_obligation", "") == "1")
        else:
            delivery_obligation = True
            master_report_obligation = True
        parts = agent_id.split("-")
        master_id = ""
        if len(parts) == 2 and len(parts[1]) == 3:
            master_id = f"{parts[0]}-1{parts[1][1:]}"

        report_id = ""
        if master_id and master_id != agent_id:
            report_id = master_report_for_turn(
                client, state, agent_id, master_id, current_turn_id)

        missing = []
        if (delivery_obligation
                and correlation_id and is_valid_agent_id(requester)
                and requester != agent_id
                and not event_exists(
                    client, agent_id, requester, correlation_id, started_at)):
            missing.append(
                f"livraison corrélée vers {requester} "
                f"(TASK_ID={task_id}, CYCLE={cycle}, "
                f"CORRELATION_ID={correlation_id})")
        if (master_report_obligation
                and master_id and master_id != agent_id
                and not report_id):
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
