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


def test_business_events_open_end_of_turn_guards():
    """Arbitrage 2026-07-28 : MESSAGE/DISPATCH/INFO_REQUIRED sont gardés ;
    l'événement vide (enveloppe legacy hors send.sh) et DECISION_REQUIRED
    ne le sont plus — c'était la classe majeure de faux positifs."""
    agent = _agent()
    assert agent._requires_correlated_event(_task(event="DISPATCH"))
    assert agent._requires_correlated_event(_task(event="MESSAGE"))
    assert agent._requires_correlated_event(_task(event="INFO_REQUIRED"))
    assert not agent._requires_correlated_event(_task(event=""))
    assert not agent._requires_correlated_event(
        _task(event="DECISION_REQUIRED"))


def test_api_retry_preserves_complete_envelope():
    agent = _agent()
    task = _task(
        event="DISPATCH", expected_event="DONE|BLOCKED",
        requester="334-134", owner="334-334", verify_cmd="true",
        custom_field="keep-me")
    retry = agent._api_retry_task(task, 0)
    assert retry["event"] == "DISPATCH"
    assert retry["expected_event"] == "DONE|BLOCKED"
    assert retry["requester"] == "334-134"
    assert retry["owner"] == "334-334"
    assert retry["custom_field"] == "keep-me"
    assert retry["_retry_count"] == 1


def test_wal_accepts_business_event_field():
    from agent import TmuxAgent
    agent = _agent()
    agent._wal = TmuxAgent._wal.__get__(agent, TmuxAgent)
    agent._wal("event_suppressed", "task-128", event="DONE")
    assert agent.redis.xadd.called


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


# ── C4 : le retry API préserve l'enveloppe complète du tour ──────────────────

def test_c4_api_retry_preserves_unguarded_event():
    """Un tour non gardé (event hors ensemble corrélé) le reste après un
    retry API : l'événement survit à la copie, le faux positif de fin de
    tour ne se rouvre pas (avant le fix, event perdu = "" = gardé)."""
    agent = _agent()
    task = _task(event="PROGRESS", _turn_id="t7", _turn_started_at=42)
    assert not agent._requires_correlated_event(task)
    retry = agent._api_retry_task(task, 0)
    assert retry["event"] == "PROGRESS"
    assert retry["_retry_count"] == 1
    assert retry["_turn_id"] == "t7"
    assert retry["_turn_started_at"] == 42
    assert not agent._requires_correlated_event(retry)


def test_c4_api_retry_preserves_business_dispatch_envelope():
    agent = _agent()
    task = _task(event="DISPATCH", expected_event="DONE",
                 owner="334-134", _turn_id="t8", _protocol_retry=1)
    retry = agent._api_retry_task(task, 1)
    for key in ("event", "expected_event", "from_agent", "owner",
                "correlation_id", "task_id", "cycle", "_turn_id",
                "_protocol_retry"):
        assert retry.get(key) == task.get(key), key
    assert retry["_retry_count"] == 2
    assert agent._requires_correlated_event(retry)


def test_terminal_pending_is_observable_but_not_a_completion():
    agent = _agent()
    assert agent._publish_terminal_pending(
        _task(), missing_correlated=True, missing_master_report=False)
    stream, fields = agent.redis.xadd.call_args.args[:2]
    assert stream == "agent:334-334:control"
    assert fields["event"] == "TERMINAL_PENDING"
    assert fields["correlation_id"] == "corr-8"
    assert fields["missing_correlated"] == "1"
    assert "completion" not in stream
    agent.redis.hset.assert_called_once()


def _load_stop_guard():
    path = os.path.join(ROOT, "scripts", "claude-stop-guard.py")
    spec = importlib.util.spec_from_file_location("claude_stop_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stop_hook_blocks_direct_turn_without_master_report(monkeypatch):
    """Fallback fail-closed : hash sans champs d'obligation (bridge non
    redémarré) = sémantique v3.2.12, la garde n'est jamais inerte."""
    guard = _load_stop_guard()
    client = MagicMock()
    client.hgetall.return_value = {}
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-334")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    assert guard.main() == 2


def test_stop_hook_allows_turn_with_explicit_zero_obligations(monkeypatch):
    """Un bridge neuf qui déclare explicitement zéro obligation pour le
    tour (contrôle, doublon, consommation) libère la fin de tour."""
    guard = _load_stop_guard()
    client = MagicMock()
    client.hgetall.return_value = {
        "current_delivery_obligation": "0",
        "current_master_report_obligation": "0",
    }
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-334")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    assert guard.main() == 0


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
        "current_delivery_obligation": "1",
        "current_master_report_obligation": "1",
    }
    client.xrevrange.return_value = []
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-334")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    assert guard.main() == 2
    assert "Fin de tour refusée" in capsys.readouterr().err
