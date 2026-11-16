"""Le Stop Hook ne bloque que les tours ayant une obligation explicite."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "claude-stop-guard.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("claude_stop_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_guard(monkeypatch, state):
    guard = load_guard()
    client = MagicMock()
    client.hgetall.return_value = state
    client.xrevrange.return_value = []
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-234")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    return guard.main(), client


def test_auto_init_without_obligations_can_stop_silently(monkeypatch):
    rc, client = run_guard(monkeypatch, {
        "current_turn_kind": "AUTO_INIT",
        "current_delivery_obligation": "0",
        "current_master_report_obligation": "0",
    })
    assert rc == 0
    client.xrevrange.assert_not_called()


def test_control_without_obligations_can_stop_silently(monkeypatch):
    rc, _ = run_guard(monkeypatch, {
        "current_turn_kind": "CONTROL",
        "current_delivery_obligation": "0",
        "current_master_report_obligation": "0",
    })
    assert rc == 0


def test_dispatch_missing_delivery_and_master_report_is_blocked(
        monkeypatch, capsys):
    rc, _ = run_guard(monkeypatch, {
        "current_turn_kind": "TASK",
        "current_delivery_obligation": "1",
        "current_master_report_obligation": "1",
        "current_correlation": "corr-1",
        "current_requester": "334-134",
        "current_task_id": "task-1",
        "current_cycle": "1",
        "current_task_started_at": "10",
    })
    assert rc == 2
    error = capsys.readouterr().err
    assert "livraison corrélée vers 334-134" in error
    assert "MASTER_REPORT vers 334-134" in error


def test_cli_worker_requires_only_master_report(monkeypatch, capsys):
    rc, _ = run_guard(monkeypatch, {
        "current_turn_kind": "CLI",
        "current_delivery_obligation": "0",
        "current_master_report_obligation": "1",
    })
    assert rc == 2
    error = capsys.readouterr().err
    assert "livraison corrélée" not in error
    assert "MASTER_REPORT vers 334-134" in error


def test_supervision_blocking_wake_never_satisfies_business_delivery(
        monkeypatch, capsys):
    """Le réveil de secours du rapport informe le Master ; il ne remplace
    jamais le terminal/send canonique dû par l'agent au demandeur.
    """
    guard = load_guard()
    client = MagicMock()
    client.hgetall.return_value = {
        "current_turn_kind": "TASK",
        "current_delivery_obligation": "1",
        "current_master_report_obligation": "0",
        "current_correlation": "corr-1",
        "current_requester": "334-134",
        "current_task_id": "task-1",
        "current_cycle": "1",
        "current_task_started_at": "10",
    }
    client.xrevrange.side_effect = lambda stream, count=200: (
        [("12-0", {
            "from_agent": "334-234",
            "to_agent": "334-134",
            "event": "DECISION_REQUIRED",
            "source_event": "INFO_REQUIRED",
            "classification": "supervision_blocking",
            "correlation_id": "corr-1",
            "timestamp": "11",
        })]
        if stream == "agent:334-134:inbox" else [])
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-234")
    monkeypatch.setattr(guard, "redis_client", lambda: client)

    assert guard.main() == 2
    assert "livraison corrélée vers 334-134" in capsys.readouterr().err


# --- F-2 (c17) : alignement du stop-guard sur AGENT.md ---------------------

def test_history_hint_auto_init_never_blocks_even_with_report_obligation(
        monkeypatch):
    """NO_NEW_WORK / indice d'historique (AUTO_INIT) : fin acceptée sans
    rapport, même si un drapeau d'obligation est resté armé (constat a)."""
    rc, client = run_guard(monkeypatch, {
        "current_turn_kind": "AUTO_INIT",
        "current_master_report_obligation": "1",
        "current_delivery_obligation": "1",
    })
    assert rc == 0
    client.xrevrange.assert_not_called()


def test_control_turn_never_blocks_even_with_obligations(monkeypatch):
    """Un tour de contrôle/supervision se termine sans rapport ni livraison."""
    rc, client = run_guard(monkeypatch, {
        "current_turn_kind": "CONTROL",
        "current_master_report_obligation": "1",
        "current_delivery_obligation": "1",
        "current_correlation": "corr-1",
        "current_requester": "334-534",
        "current_task_id": "task-1",
        "current_cycle": "1",
        "current_task_started_at": "10",
    })
    assert rc == 0
    client.xrevrange.assert_not_called()


def _run_guard_streams(monkeypatch, state, streams):
    guard = load_guard()
    client = MagicMock()
    client.hgetall.return_value = state
    client.xrevrange.side_effect = (
        lambda stream, count=200: streams.get(stream, []))
    monkeypatch.setattr(guard, "hook_input", lambda: {})
    monkeypatch.setattr(guard, "current_agent_id", lambda: "334-234")
    monkeypatch.setattr(guard, "redis_client", lambda: client)
    return guard.main()


def test_non_terminal_message_does_not_require_delivery(monkeypatch):
    """Un MESSAGE entrant non terminal (expected_event vide) n'exige pas de
    livraison corrélée : la fin de tour est acceptée (constat b)."""
    rc = _run_guard_streams(
        monkeypatch,
        {
            "current_turn_kind": "TASK",
            "current_delivery_obligation": "1",
            "current_master_report_obligation": "0",
            "current_correlation": "corr-1",
            "current_requester": "334-534",
            "current_task_id": "task-1",
            "current_cycle": "1",
            "current_task_started_at": "10",
        },
        {
            "agent:334-234:inbox": [("5-0", {
                "from_agent": "334-534",
                "event": "MESSAGE",
                "expected_event": "",
                "correlation_id": "corr-1",
                "timestamp": "9",
            })],
        },
    )
    assert rc == 0


def test_real_dispatch_still_requires_delivery(monkeypatch, capsys):
    """Témoin : un vrai DISPATCH (expected_event renseigné) reste gardé."""
    rc = _run_guard_streams(
        monkeypatch,
        {
            "current_turn_kind": "TASK",
            "current_delivery_obligation": "1",
            "current_master_report_obligation": "0",
            "current_correlation": "corr-1",
            "current_requester": "334-534",
            "current_task_id": "task-1",
            "current_cycle": "1",
            "current_task_started_at": "10",
        },
        {
            "agent:334-234:inbox": [("5-0", {
                "from_agent": "334-534",
                "event": "DISPATCH",
                "expected_event": "DONE",
                "correlation_id": "corr-1",
                "timestamp": "9",
            })],
        },
    )
    assert rc == 2
    assert "livraison corrélée vers 334-534" in capsys.readouterr().err
