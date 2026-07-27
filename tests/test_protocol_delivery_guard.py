"""Fin de tour inter-agent : livraison explicite et escalade corrélée."""

import os
import sys
import importlib.util
from unittest.mock import MagicMock


ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "agent-bridge"))


def _agent():
    from agent import TmuxAgent
    instance = object.__new__(TmuxAgent)
    instance.agent_id = "334-334"
    instance.redis = MagicMock()
    instance._log = MagicMock()
    instance._wal = MagicMock()
    return instance


def _task(**extra):
    task = {
        "source": "redis",
        "from_agent": "334-134",
        "correlation_id": "corr-8",
        "task_id": "task-128",
        "cycle": "8",
    }
    task.update(extra)
    return task


def test_cli_and_uncorrelated_turns_are_not_guarded():
    agent = _agent()
    assert not agent._requires_correlated_event(
        _task(from_agent="cli"))
    assert not agent._requires_correlated_event(
        _task(correlation_id=""))


def test_done_event_satisfies_guard():
    agent = _agent()
    agent.redis.xrevrange.side_effect = lambda stream, count=200: (
        [("1-0", {"correlation_id": "corr-8", "from": "334-334"})]
        if stream == "completion" else [])
    assert agent._has_correlated_business_event(_task())


def test_intermediate_send_event_satisfies_guard():
    agent = _agent()
    agent.redis.xrevrange.side_effect = lambda stream, count=200: (
        [("2-0", {
            "correlation_id": "corr-8",
            "from_agent": "334-334",
            "event": "PROGRESS",
        })] if stream == "agent:334-134:inbox" else [])
    assert agent._has_correlated_business_event(_task())


def test_protocol_error_is_correlated_and_never_done():
    agent = _agent()
    agent.redis.set.return_value = True
    assert agent._publish_protocol_error(_task())
    calls = agent.redis.xadd.call_args_list
    completion = calls[0].args[1]
    requester_event = calls[1].args[1]
    assert completion["event"] == "PROTOCOL_ERROR"
    assert completion["origin"] == "bridge"
    assert requester_event["event"] == "PROTOCOL_ERROR"
    assert requester_event["correlation_id"] == "corr-8"
    assert "prompt" not in requester_event
    assert requester_event["classification"] == "control"


def _load_stop_guard():
    path = os.path.join(ROOT, "scripts", "claude-stop-guard.py")
    spec = importlib.util.spec_from_file_location("claude_stop_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stop_hook_blocks_direct_turn_without_master_report(monkeypatch):
    guard = _load_stop_guard()
    client = MagicMock()
    client.hgetall.return_value = {}
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-334")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    assert guard.main() == 2


def test_stop_hook_allows_direct_turn_after_new_master_report(monkeypatch):
    guard = _load_stop_guard()
    client = MagicMock()
    client.hgetall.return_value = {
        "last_master_report_id": "turn-new",
        "last_stop_master_report_id": "turn-old",
    }
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-334")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    assert guard.main() == 0
    client.hset.assert_called_with(
        "agent:334-334", "last_stop_master_report_id", "turn-new")


def test_stop_hook_blocks_correlated_turn_without_event(monkeypatch, capsys):
    guard = _load_stop_guard()
    client = MagicMock()
    client.hgetall.return_value = {
        "current_correlation": "corr-8",
        "current_requester": "334-134",
        "current_task_id": "task-128",
        "current_cycle": "8",
        "current_task_started_at": "1",
    }
    client.xrevrange.return_value = []
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-334")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    assert guard.main() == 2
    assert "Fin de tour refusée" in capsys.readouterr().err
