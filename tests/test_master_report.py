"""Rapport obligatoire de fin de tour au coordinateur du triangle."""

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "scripts" / "report-master.sh"
DONE = ROOT / "scripts" / "done.sh"
SEND = ROOT / "scripts" / "send.sh"
SENDER = "712-812"
MASTER = "712-112"


def shell(command):
    return subprocess.run(
        ["bash", "-c", command], cwd=ROOT, capture_output=True, text=True)


def private_redis_env(redis_client, **extra):
    """Environnement subprocess pointant exclusivement vers le Redis fixture.

    Une regression de ``redis.sh`` vers le port implicite 6379 ne doit jamais
    rendre ces tests verts par accident : l'hote, le port, la DB et le mot de
    passe sont tous explicites.
    """
    connection = redis_client.connection_pool.connection_kwargs
    env = os.environ.copy()
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    env.update({
        "REDIS_HOST": str(connection["host"]),
        "REDIS_PORT": str(connection["port"]),
        "REDIS_DB": str(connection.get("db", 0)),
        "REDIS_PASSWORD": "",
        "FROM_AGENT": SENDER,
    })
    env.update({key: str(value) for key, value in extra.items()})
    return env


def turn_env(redis_client, turn="turn-report-1", **extra):
    values = {
        "TURN_ID": turn,
        "TASK_ID": "task-report",
        "CYCLE": "7",
        "CORRELATION_ID": "corr-report",
        "REQUESTER_ID": MASTER,
        "OWNER_ID": SENDER,
        "TURN_ORIGIN": "bridge",
    }
    values.update(extra)
    return private_redis_env(redis_client, **values)


def run_report(redis_client, status, summary="Résumé factuel", **env_extra):
    return subprocess.run(
        ["bash", str(REPORT), status, summary],
        cwd=ROOT,
        env=turn_env(redis_client, **env_extra),
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_done(redis_client, signal="INFO_REQUIRED", details="Décision requise",
             **env_extra):
    return subprocess.run(
        ["bash", str(DONE), MASTER, signal, details],
        cwd=ROOT,
        env=turn_env(redis_client, **env_extra),
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_send(redis_client, target=MASTER, message="Décision requise",
             **env_extra):
    env_extra.setdefault("MESSAGE_EVENT", "INFO_REQUIRED")
    return subprocess.run(
        ["bash", str(SEND), target, message], cwd=ROOT,
        env=turn_env(redis_client, **env_extra), capture_output=True,
        text=True, timeout=15)


def one_entry(redis_client, stream):
    entries = redis_client.xrange(stream)
    assert len(entries) == 1
    return entries[0]


def test_triangle_master_is_derived_without_hardcoded_examples():
    result = shell(
        "source scripts/lib.sh; triangle_master_id 712-845")
    assert result.returncode == 0
    assert result.stdout.strip() == "712-145"


def test_triangle_master_rejects_self_and_global_ids():
    assert shell("source scripts/lib.sh; triangle_master_id 712-145").returncode
    assert shell("source scripts/lib.sh; triangle_master_id 712").returncode


def test_report_script_uses_non_interactive_supervision_stream():
    source = (ROOT / "scripts" / "report-master.sh").read_text()
    assert "bus_protocol.py" in source
    assert " report " in source
    assert "XADD" not in source, (
        "le wrapper ne doit pas recréer une publication partielle hors Lua")


@pytest.mark.parametrize(
    ("status", "expected_event", "expected_classification"),
    [
        ("SUCCESS", "MASTER_REPORT", "supervision_progress"),
        ("PARTIAL", "MASTER_REPORT", "supervision_progress"),
        ("FAILED", "MASTER_REPORT", "supervision_progress"),
        ("BLOCKED", "DECISION_REQUIRED", "supervision_blocking"),
        ("INFO_REQUIRED", "DECISION_REQUIRED", "supervision_blocking"),
    ],
)
def test_five_report_statuses_are_atomic_and_delivered(
        redis_client, status, expected_event, expected_classification):
    redis_client.flushdb()

    result = run_report(redis_client, status)

    assert result.returncode == 0, result.stderr
    assert "state=STORED" in result.stdout
    assert "decision_id=decision-" in result.stdout
    _stream_id, report = one_entry(redis_client, f"agent:{MASTER}:reports")
    assert report["schema"] == "ma.bus.v1"
    assert report["schema_version"] == "ma.bus.v1"
    assert report["event"] == "MASTER_REPORT"
    assert report["classification"] == "supervision"
    assert report["status"] == status
    assert report["source_turn_id"] == "turn-report-1"
    assert report["turn_id"] == "turn-report-1"
    assert report["task_id"] == "task-report"
    assert report["cycle"] == "7"
    assert report["source_correlation"] == "corr-report"
    assert report["report_id"].startswith("report-")
    assert report["event_id"].startswith("event-")
    assert report["decision_id"].startswith("decision-")
    assert redis_client.xlen(f"agent:{MASTER}:inbox") == 1

    state = redis_client.hgetall(f"agent:{SENDER}")
    assert state["last_master_report_id"] == report["report_id"]
    assert state["last_master_report_source_turn_id"] == "turn-report-1"
    assert state["last_master_report_status"] == status
    assert state["last_master_report_schema"] == "ma.bus.v1"

    _wake_id, wake = one_entry(redis_client, f"agent:{MASTER}:inbox")
    assert wake["schema"] == "ma.bus.v1"
    assert wake["schema_version"] == "ma.bus.v1"
    assert wake["event"] == expected_event
    assert wake["source_event"] == status
    assert wake["status"] == status
    assert wake["classification"] == expected_classification
    assert wake["source_turn_id"] == report["source_turn_id"]
    assert wake["decision_id"] == report["decision_id"]
    assert wake["related_report_id"] == report["report_id"]
    assert state["last_master_report_delivery"] == "DELIVERED"


def test_report_recovers_complete_context_from_sender_state(redis_client):
    redis_client.flushdb()
    redis_client.hset(f"agent:{SENDER}", mapping={
        "current_turn_id": "state-turn-9",
        "current_task_id": "task-from-state",
        "current_cycle": "9",
        "current_correlation": "corr-from-state",
        "current_requester": MASTER,
        "current_owner": SENDER,
        "current_turn_origin": "redis-bridge",
    })
    env = private_redis_env(redis_client)

    result = subprocess.run(
        ["bash", str(REPORT), "INFO_REQUIRED", "Contexte récupéré"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)

    assert result.returncode == 0, result.stderr
    _stream_id, report = one_entry(redis_client, f"agent:{MASTER}:reports")
    assert report["source_turn_id"] == "state-turn-9"
    assert report["task_id"] == "task-from-state"
    assert report["cycle"] == "9"
    assert report["source_correlation"] == "corr-from-state"
    assert report["requester"] == MASTER
    assert report["owner"] == SENDER
    assert report["origin"] == "redis-bridge"


def test_identical_report_replay_is_idempotent(redis_client):
    redis_client.flushdb()

    first = run_report(redis_client, "INFO_REQUIRED")
    second = run_report(redis_client, "INFO_REQUIRED")

    assert first.returncode == second.returncode == 0
    assert redis_client.xlen(f"agent:{MASTER}:reports") == 1
    inbox_entries = redis_client.xrange(f"agent:{MASTER}:inbox")
    assert len(inbox_entries) == 1, inbox_entries
    assert "REPLAY" in second.stdout or "ALREADY" in second.stdout


def test_changed_payload_in_same_turn_is_a_conflict_with_zero_extra_effect(
        redis_client):
    redis_client.flushdb()
    first = run_report(redis_client, "INFO_REQUIRED", "Question A")
    before_state = redis_client.hgetall(f"agent:{SENDER}")

    conflict = run_report(redis_client, "INFO_REQUIRED", "Question B")

    assert first.returncode == 0
    assert conflict.returncode == 3
    assert "CONFLICT" in conflict.stdout or "conflict" in conflict.stderr.lower()
    assert redis_client.xlen(f"agent:{MASTER}:reports") == 1
    assert redis_client.xlen(f"agent:{MASTER}:inbox") == 1
    assert redis_client.hgetall(f"agent:{SENDER}") == before_state


def test_same_payload_and_correlation_in_a_new_turn_is_a_new_decision(
        redis_client):
    redis_client.flushdb()

    first = run_report(redis_client, "BLOCKED", turn="turn-a")
    second = run_report(redis_client, "BLOCKED", turn="turn-b")

    assert first.returncode == second.returncode == 0
    assert redis_client.xlen(f"agent:{MASTER}:reports") == 2
    assert redis_client.xlen(f"agent:{MASTER}:inbox") == 2
    reports = [fields for _entry_id, fields in
               redis_client.xrange(f"agent:{MASTER}:reports")]
    assert {entry["source_turn_id"] for entry in reports} == {
        "turn-a", "turn-b"}
    assert len({entry["decision_id"] for entry in reports}) == 2


def test_wrongtype_precheck_has_zero_partial_publication(redis_client):
    redis_client.flushdb()
    inbox = f"agent:{MASTER}:inbox"
    redis_client.set(inbox, "wrong-type-sentinel")

    result = run_report(redis_client, "BLOCKED")

    assert result.returncode == 1
    assert "TYPE_PRECHECK" in result.stderr
    assert redis_client.get(inbox) == "wrong-type-sentinel"
    assert redis_client.xlen(f"agent:{MASTER}:reports") == 0
    assert not redis_client.exists(f"agent:{SENDER}")
    assert list(redis_client.scan_iter("ma:bus:v1:report:*")) == []
    assert list(redis_client.scan_iter("ma:bus:v1:decision:*")) == []


@pytest.mark.parametrize("order", ["report-first", "terminal-first"])
def test_blocking_report_and_terminal_deliver_one_master_inbox_event(
        redis_client, order):
    redis_client.flushdb()
    operations = {
        "report": lambda: run_report(
            redis_client, "INFO_REQUIRED", "Même décision"),
        "terminal": lambda: run_done(
            redis_client, "INFO_REQUIRED", "Même décision"),
    }
    sequence = (
        ("report", "terminal") if order == "report-first"
        else ("terminal", "report"))

    results = [operations[name]() for name in sequence]

    # done.sh peut retourner ORPHANED (2) quand aucun pane tmux de test
    # n'existe ; la publication Redis a néanmoins réussi et fait foi.
    assert results[0].returncode in (0, 2), results[0].stderr
    assert results[1].returncode in (0, 2), results[1].stderr
    assert redis_client.xlen(f"agent:{MASTER}:reports") == 1
    assert redis_client.xlen("completion") == 1
    assert redis_client.xlen(f"agent:{MASTER}:inbox") == 1
    _entry_id, delivered = one_entry(redis_client, f"agent:{MASTER}:inbox")
    assert delivered["decision_id"].startswith("decision-")
    assert delivered["source_turn_id"] == "turn-report-1"


@pytest.mark.parametrize("order", ["report-first", "send-first"])
def test_blocking_report_and_send_to_same_master_deliver_one_inbox_event(
        redis_client, order):
    redis_client.flushdb()
    operations = {
        "report": lambda: run_report(
            redis_client, "INFO_REQUIRED", "Même décision"),
        "send": lambda: run_send(redis_client, MASTER, "Même décision"),
    }
    sequence = (
        ("report", "send") if order == "report-first"
        else ("send", "report"))

    results = [operations[name]() for name in sequence]

    assert all(result.returncode in (0, 2) for result in results)
    assert redis_client.xlen(f"agent:{MASTER}:reports") == 1
    inbox_entries = redis_client.xrange(f"agent:{MASTER}:inbox")
    decision_id = inbox_entries[0][1]["decision_id"]
    ledger = redis_client.hgetall(f"ma:bus:v1:decision:{decision_id}")
    assert len(inbox_entries) == 1, (inbox_entries, ledger, [
        (result.stdout, result.stderr) for result in results])


def test_blocking_report_and_send_to_different_targets_are_each_delivered(
        redis_client):
    redis_client.flushdb()
    other_target = "712-912"

    report = run_report(redis_client, "INFO_REQUIRED", "Même décision")
    sent = run_send(redis_client, other_target, "Même décision")

    assert report.returncode == 0
    assert sent.returncode in (0, 2)
    assert redis_client.xlen(f"agent:{MASTER}:inbox") == 1
    assert redis_client.xlen(f"agent:{other_target}:inbox") == 1


@pytest.mark.parametrize("publisher", ["send", "terminal"])
def test_replay_reports_that_duplicate_decision_wake_was_suppressed(
        redis_client, publisher):
    redis_client.flushdb()
    report = run_report(redis_client, "INFO_REQUIRED", "Même décision")
    operation = (
        (lambda: run_send(redis_client, MASTER, "Même décision"))
        if publisher == "send"
        else (lambda: run_done(redis_client, "INFO_REQUIRED", "Même décision")))

    first = operation()
    replay = operation()

    assert report.returncode == 0
    assert first.returncode == replay.returncode == 0
    assert "state=SUPPRESSED_BY_DECISION" in first.stdout
    assert "state=ALREADY_SUPPRESSED_BY_DECISION" in replay.stdout
    assert redis_client.xlen(f"agent:{MASTER}:inbox") == 1


def test_upgrade_merges_hook_without_replacing_existing_hooks(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{
            "type": "command", "command": "existing-check"
        }]}]},
        "env": {"KEPT": "yes"},
    }))
    path = ROOT / "patch" / "merge-communication-hooks.py"
    first = subprocess.run(
        ["python3", str(path), str(target)], capture_output=True, text=True)
    second = subprocess.run(
        ["python3", str(path), str(target)], capture_output=True, text=True)
    assert first.returncode == second.returncode == 0
    data = json.loads(target.read_text())
    commands = [
        hook["command"]
        for group in data["hooks"]["Stop"]
        for hook in group["hooks"]
    ]
    assert "existing-check" in commands
    assert sum("claude-stop-guard.py" in command for command in commands) == 1
    assert data["env"]["KEPT"] == "yes"
