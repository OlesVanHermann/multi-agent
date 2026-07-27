"""Les événements non actionnables ne doivent consommer aucun tour modèle."""

from queue import Queue
from threading import Lock
from unittest.mock import MagicMock

import event_router
from agent import TmuxAgent


def bridge(agent_id):
    instance = object.__new__(TmuxAgent)
    instance.agent_id = agent_id
    instance.redis = MagicMock()
    instance.metrics = None
    instance.prompt_queue = Queue()
    instance._inflight_ids = set()
    instance._inflight_lock = Lock()
    instance._log = MagicMock()
    instance._wal = MagicMock()
    instance._ack_inbox = MagicMock()
    instance.redis.set.return_value = True
    instance.redis.hget.return_value = None
    instance.redis.xrange.return_value = []
    return instance


def envelope(event, **extra):
    data = {
        "type": "prompt",
        "prompt": f"EVENT:{event}",
        "from_agent": "334-334",
        "event": event,
        "task_id": "task-1",
        "cycle": "1",
        "correlation_id": "corr-1",
    }
    data.update(extra)
    return data


def test_event_taxonomy():
    assert event_router.classify(envelope("DISPATCH")) == "actionable"
    assert event_router.classify(envelope("DONE")) == "terminal"
    assert event_router.classify(envelope("MASTER_REPORT")) == "supervision"
    assert event_router.classify(envelope("PROTOCOL_ERROR")) == "control"
    assert event_router.classify(envelope("UNATTRIBUTED")) == "quarantine"


def test_thousand_control_events_produce_zero_model_turns():
    agent = bridge("334-334")
    for number in range(1000):
        agent._handle_inbox_message(
            f"{number}-0",
            envelope("PROTOCOL_ERROR", correlation_id=f"corr-{number}"))
    assert agent.prompt_queue.qsize() == 0
    assert agent._ack_inbox.call_count == 1000


def test_master_report_is_stored_without_model_turn():
    agent = bridge("334-134")
    agent._handle_inbox_message("1-0", envelope("MASTER_REPORT"))
    assert agent.prompt_queue.empty()
    stream = agent.redis.xadd.call_args.args[0]
    fields = agent.redis.xadd.call_args.args[1]
    assert stream == "agent:334-134:supervision"
    assert fields["classification"] == "supervision"


def test_terminal_to_worker_is_stored_without_model_turn():
    agent = bridge("334-834")
    agent._handle_inbox_message("1-0", envelope("DONE"))
    assert agent.prompt_queue.empty()


def test_new_terminal_to_master_creates_one_decision_turn():
    agent = bridge("334-134")
    agent._handle_inbox_message("1-0", envelope("DONE"))
    assert agent.prompt_queue.qsize() == 1
    task = agent.prompt_queue.get_nowait()
    assert task["event"] == "DECISION_REQUIRED"
    assert not agent._requires_correlated_event(task)
    assert not agent._requires_master_report(task)


def test_duplicate_terminal_never_creates_second_turn():
    agent = bridge("334-134")
    agent.redis.set.side_effect = [True, False]
    agent._handle_inbox_message("1-0", envelope("DONE"))
    agent._handle_inbox_message("2-0", envelope("DONE"))
    assert agent.prompt_queue.qsize() == 1


def test_bridge_and_watchdog_share_protocol_error_dedup_namespace():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    bridge_source = (
        root / "scripts" / "agent-bridge" / "agent.py").read_text()
    watchdog_source = (
        root / "scripts" / "agent-bridge" / "healthcheck.py").read_text()
    marker = 'f"protocol_error:{'
    assert marker in bridge_source
    assert marker in watchdog_source
    assert "watchdog:protocol_error:" not in watchdog_source
