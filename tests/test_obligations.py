"""Non-régression des obligations durables de communication."""

import importlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import obligations


ROOT = Path(__file__).resolve().parents[1]


def dispatch(task="task-1", cycle="1", corr="corr-1", expected="ARBITRAGE"):
    return {
        "event": "DISPATCH",
        "expected_event": expected,
        "requester": "303-103",
        "owner": "303-303",
        "correlation_id": corr,
        "task_id": task,
        "cycle": cycle,
    }


def test_dispatch_creates_a_durable_obligation(tmp_path):
    path = obligations.create(tmp_path, "303-303", dispatch(), "1-0", now=10)
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["owner"] == "303-303"
    assert data["expected_event"] == "ARBITRAGE"
    assert data["correlation_id"] == "corr-1"
    assert data["received_at"] == 10
    assert data["status"] == "OPEN"


def test_non_dispatch_does_not_create_obligation(tmp_path):
    message = dispatch()
    message["event"] = "STATUS"
    assert obligations.create(tmp_path, "303-303", message, "1-0") is None
    assert list(obligations.iter_open(tmp_path) or []) == []


def test_terminal_clears_the_obligation_by_archiving(tmp_path):
    path = obligations.create(tmp_path, "303-303", dispatch(), "1-0", now=10)
    archived = obligations.close(
        tmp_path, "task-1", "1", "303-303", "corr-1", "ARBITRAGE", now=20)
    assert archived.is_file()
    assert not path.exists()
    data = json.loads(archived.read_text())
    assert data["status"] == "DELIVERED"
    assert data["delivered_at"] == 20


def test_done_sh_closes_obligation_after_completion_before_inbox():
    source = (ROOT / "scripts" / "done.sh").read_text()
    completion = source.index('if [ -z "$COMPLETION_ID" ]')
    cleanup = source.index("close_obligation", completion)
    inbox = source.index("# 2. Délivrance : inbox de la cible", cleanup)
    assert completion < cleanup < inbox


def test_wrong_terminal_does_not_close_obligation(tmp_path):
    path = obligations.create(tmp_path, "303-303", dispatch(), "1-0", now=10)
    assert obligations.close(
        tmp_path, "task-1", "1", "303-303", "corr-1", "DONE") is None
    assert path.is_file()


def test_same_corr_different_cycles_are_distinct(tmp_path):
    first = obligations.create(
        tmp_path, "303-303", dispatch(cycle="r1"), "1-0", now=10)
    second = obligations.create(
        tmp_path, "303-303", dispatch(cycle="r2"), "2-0", now=11)
    assert first != second
    assert first.is_file() and second.is_file()


def test_obligation_survives_redis_flush(tmp_path, redis_client):
    path = obligations.create(tmp_path, "303-303", dispatch(), "1-0", now=10)
    redis_client.flushall()
    assert path.is_file()
    assert len(list(obligations.iter_open(tmp_path))) == 1


def test_completion_reconciles_open_obligation(tmp_path, redis_client):
    obligations.create(tmp_path, "303-303", dispatch(), "1-0", now=10)
    redis_client.xadd("completion", {
        "from": "303-303",
        "event": "ARBITRAGE",
        "task_id": "task-1",
        "cycle": "1",
        "correlation_id": "corr-1",
    })
    closed = obligations.reconcile(redis_client, tmp_path)
    assert len(closed) == 1
    assert list(obligations.iter_open(tmp_path) or []) == []


def test_bridge_propagates_expected_event_and_creates_obligation(
        tmp_path, monkeypatch):
    agent_module = importlib.import_module("agent")
    agent = object.__new__(agent_module.TmuxAgent)
    agent.agent_id = "303-303"
    agent.prompt_queue = __import__("queue").Queue()
    agent._inflight_ids = set()
    agent._inflight_lock = __import__("threading").Lock()
    agent.metrics = None
    agent.redis = MagicMock()
    agent._log = MagicMock()
    monkeypatch.setattr(agent_module, "BASE_DIR", tmp_path)
    agent._handle_inbox_message("1-0", {
        "prompt": "travaille",
        "from_agent": "303-103",
        **dispatch(),
    })
    task = agent.prompt_queue.get_nowait()
    assert task["event"] == "DISPATCH"
    assert task["expected_event"] == "ARBITRAGE"
    assert task["requester"] == "303-103"
    assert task["owner"] == "303-303"
    assert obligations.obligation_path(
        tmp_path, "task-1", "1", "303-303").is_file()


def test_open_obligation_is_reminded_then_escalated(
        tmp_path, redis_client, monkeypatch):
    healthcheck = importlib.import_module("healthcheck")
    path = obligations.create(
        tmp_path, "303-303", dispatch(corr="corr-reminder"), "1-0", now=100)
    watchdog = healthcheck.AgentWatchdog(
        redis_client, obligation_reminder_s=10, base_dir=tmp_path)
    sent = []

    def fake_send(agent_id, data, message):
        sent.append((agent_id, data, message))
        return subprocess.CompletedProcess([], 0, "state=DELIVERED", "")

    monkeypatch.setattr(watchdog, "_send_status_required", fake_send)
    first = watchdog._check_obligations(now=111)
    assert first["303-303"] == "obligation_reminded"
    assert len(sent) == 1
    assert all(token in sent[0][2] for token in (
        "TASK=task-1", "CYCLE=1", "CORR=corr-reminder",
        "EXPECTED_EVENT=ARBITRAGE"))
    assert json.loads(path.read_text())["reminder_at"] == 111

    second = watchdog._check_obligations(now=121)
    assert second["303-303"] == "obligation_escalated"
    assert json.loads(path.read_text())["escalated_at"] == 121
    events = [data for _, data in redis_client.xrange("wal")]
    assert any(data["event"] == "obligation_reminder" for data in events)
    assert any(data["event"] == "obligation_escalation" for data in events)


def test_response_published_is_recorded_before_ack():
    source = (ROOT / "scripts" / "agent-bridge" / "agent.py").read_text()
    response_index = source.index('"response_published"')
    ack_index = source.index(
        "# A4: ack only after the response is published to the outbox",
        response_index)
    assert response_index < ack_index


def test_watchdog_lifecycle_precedes_redis_flush():
    source = (ROOT / "scripts" / "infra.sh").read_text()
    assert "start_watchdog" in source
    stop = source[source.index("do_stop()"):source.index("# ── Help ──")]
    assert stop.index("stop_watchdog") < stop.index("FLUSHALL")


def test_reminder_goes_through_send_sh_not_direct_xadd():
    source = (
        ROOT / "scripts" / "agent-bridge" / "healthcheck.py").read_text()
    method = source[
        source.index("def _send_status_required"):
        source.index("def _check_obligations")
    ]
    assert '"scripts" / "send.sh"' in method
    assert ".xadd(" not in method
