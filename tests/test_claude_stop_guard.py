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
