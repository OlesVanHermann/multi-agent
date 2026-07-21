"""Régressions v3.1.4 : keepalive Codex, défaut global et sandbox systemd."""

import importlib.util
import asyncio
import json
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_scheduler():
    path = ROOT / "scripts" / "crontab-scheduler.py"
    spec = importlib.util.spec_from_file_location("crontab_scheduler_v314", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_keepalive_credential_file_is_engine_specific():
    scheduler = _load_scheduler()
    assert scheduler.ENGINE_CRED_FILE == {
        "claude": ".credentials.json",
        "codex": "auth.json",
    }


def test_codex_status_converts_percent_left_to_used(monkeypatch):
    scheduler = _load_scheduler()
    pane = """
Account: user@example.com (Pro)
Directory: ~/multi-agent
Model: gpt-5.6-sol
Weekly limit: [████] 79% left
              (resets 22:20 on 21 Jul)
GPT-5.3-Codex-Spark Weekly limit: [████] 100% left
"""
    monkeypatch.setattr(scheduler, "_pane_text", lambda _session: pane)
    monkeypatch.setattr(scheduler.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _seconds: None)
    bars, info = scheduler._scrape_codex_status("agent-002-codex1a")
    assert [b["percent"] for b in bars] == [21, 0]
    assert info["email"] == "user@example.com"
    assert info["login_method"] == "ChatGPT account"
    assert info["model"] == "gpt-5.6-sol"


def test_status_model_parser_is_shared_by_claude_and_codex():
    scheduler = _load_scheduler()
    claude = scheduler._parse_status_info(
        "Login method: Claude Max account\nModel: claude-opus-4-8\n", "claude")
    codex = scheduler._parse_status_info(
        "Account: user@example.com (Pro)\nModel: gpt-5.6-sol\n", "codex")
    assert claude["model"] == "claude-opus-4-8"
    assert codex["model"] == "gpt-5.6-sol"


def test_keepalive_websocket_ids_are_bounded():
    source = (ROOT / "web/backend/multi_agent/routers/ws.py").read_text()
    assert '_KEEPALIVE_ID_RE = re.compile(r"^002-(?:claude|codex)\\d[a-z]$")' in source
    assert "and not _KEEPALIVE_ID_RE.match(agent_id)" in source


def test_global_mutations_are_explicit_without_popup():
    models = (ROOT / "web/backend/multi_agent/models.py").read_text()
    backend = (ROOT / "web/backend/multi_agent/routers/config.py").read_text()
    frontend = (ROOT / "web/frontend/src/components/LoginModelPanel.jsx").read_text()
    assert models.count("confirm_global: bool = False") == 2
    assert backend.count('not data.confirm_global') >= 2
    assert "default_affected" in backend
    assert "Défaut global" in frontend
    assert "window.confirm" not in frontend
    assert "const confirmGlobal = agentId === 'default'" in frontend
    assert "engine_codex_preflight" in backend


def test_systemd_write_contract_is_synchronized():
    required = {"logs", "uploads", "crontab", "keepalive", "prompts"}
    dropin = (ROOT / "setup/multiagent-dashboard-hardening.conf.example").read_text()
    checker = (ROOT / "scripts/check-dashboard-systemd.sh").read_text()
    frontend_doc = (ROOT / "docs/FRONTEND.md").read_text()
    for path in required:
        assert f"/multi-agent/{path}" in dropin
        assert path in checker
        assert f"`{path}/`" in frontend_doc
    assert "EnvironmentFile=%h/multi-agent/setup/secrets.cfg" in dropin


def test_reference_profile_json_stays_valid():
    for path in (ROOT / "login").glob("claude*/settings.json"):
        json.loads(path.read_text())


def test_backend_never_spawns_first_tmux_server():
    """La garde teste le SOCKET, jamais `tmux has-session` nu : TOUTE commande
    tmux (has-session comprise) crée le socket ET le serveur — une garde à
    base de has-session provoque elle-même l'empoisonnement qu'elle doit
    empêcher (serveur né dans le namespace sandboxé → /home ro → EROFS)."""
    tmuxio = (ROOT / "web/backend/multi_agent/tmuxio.py").read_text()
    agents = (ROOT / "web/backend/multi_agent/routers/agents.py").read_text()
    config = (ROOT / "web/backend/multi_agent/routers/config.py").read_text()
    server = (ROOT / "web/backend/server.py").read_text()
    assert "def _tmux_socket_path()" in tmuxio
    assert "async def _tmux_server_alive()" in tmuxio
    assert "probe.connect(path)" in tmuxio
    assert "socket.AF_UNIX" in tmuxio
    assert '["tmux", "has-session"]' not in tmuxio
    assert "TMUX_SERVER_ABSENT_DETAIL" in tmuxio
    assert "not await _tmux_server_alive()" in agents
    assert "not await _tmux_server_alive()" in config
    # server.py : le has-session -t <session> n'est exécuté QUE si le socket
    # existe déjà ; jamais de `tmux has-session` sans cible.
    assert '["tmux", "has-session"]' not in server
    assert "await _tmux_server_alive()" in server
    assert "if _server_up else None" in server
    assert "scheduler NON démarré" in server


def test_keepalive_start_is_verified_after_spawn():
    source = (ROOT / "web/backend/multi_agent/routers/config.py").read_text()
    start = source[source.index("async def start_keepalive"):]
    assert "await asyncio.sleep(2)" in start
    assert start.count('["tmux", "has-session", "-t", session]') >= 2
    assert "morte au lancement" in start


def test_cloned_refresh_tokens_are_detected_without_exposing_secret(tmp_path, monkeypatch):
    scheduler = _load_scheduler()
    monkeypatch.setattr(scheduler, "LOGIN_DIR", str(tmp_path))
    for profile in ("codex1a", "codex2a"):
        directory = tmp_path / profile
        directory.mkdir()
        (directory / "auth.json").write_text(json.dumps({
            "tokens": {"refresh_token": "same-secret-token"}
        }))
    assert scheduler._cloned_refresh_token_profiles(["codex1a", "codex2a"]) == {
        "codex1a", "codex2a"
    }
    fingerprint = scheduler._refresh_token_fingerprint("codex1a")
    assert fingerprint and "same-secret-token" not in fingerprint


def test_cleanup_targets_only_legacy_keepalive_sessions(monkeypatch):
    scheduler = _load_scheduler()
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[:2] == ["tmux", "list-sessions"]:
            return SimpleNamespace(
                returncode=0,
                stdout=("A-agent-002-codex1a\nA-agent-300\n"
                        "agent-002-codex1a\nA-agent-002-invalid\n"),
            )
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    assert scheduler._cleanup_legacy_keepalive_sessions() == ["A-agent-002-codex1a"]
    assert ["tmux", "kill-session", "-t", "=A-agent-002-codex1a"] in calls
    assert ["tmux", "kill-session", "-t", "=A-agent-300"] not in calls


def test_systemd_path_is_portable():
    dropin = (ROOT / "setup/multiagent-dashboard-hardening.conf.example").read_text()
    assert "Environment=PATH=%h/.local/bin:" in dropin
    assert "/.nvm/versions/node/v" not in dropin


def test_tmux_socket_probe_rejects_stale_socket(monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / "web" / "backend"))
    from multi_agent import tmuxio

    class StaleSocket:
        def settimeout(self, _timeout):
            pass

        def connect(self, _path):
            raise ConnectionRefusedError("stale")

        def close(self):
            pass

    loop = asyncio.new_event_loop()
    try:
        monkeypatch.setattr(tmuxio.os.path, "exists", lambda _path: True)
        monkeypatch.setattr(tmuxio.socket, "socket", lambda *_args: StaleSocket())
        assert loop.run_until_complete(tmuxio._tmux_server_alive()) is False
    finally:
        monkeypatch.undo()
        loop.close()
