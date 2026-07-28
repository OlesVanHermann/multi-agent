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
OpenAI Codex (v0.144.5)
Model: gpt-5.6-sol (reasoning xhigh, summaries auto)
Permissions: Full Access
Agents.md: AGENTS.md
Weekly limit: [████] 79% left
              (resets 22:20 on 21 Jul)
GPT-5.3-Codex-Spark Weekly limit: [████] 100% left
"""
    monkeypatch.setattr(scheduler, "_pane_text", lambda _session, **_kwargs: pane)
    monkeypatch.setattr(scheduler.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _seconds: None)
    bars, info = scheduler._scrape_codex_status("agent-002-codex1a")
    assert [b["percent"] for b in bars] == [21, 0]
    assert info["email"] == "user@example.com"
    assert info["login_method"] == "ChatGPT account"
    assert info["model"] == "gpt-5.6-sol"
    assert info["effort"] == "xhigh"
    assert info["permissions"] == "Full Access"
    assert info["cli_version"] == "0.144.5"


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


def test_effort_ui_exposes_deferred_application_and_serializes_clicks():
    frontend = (ROOT / "web/frontend/src/components/LoginModelPanel.jsx").read_text()
    assert "detail.applied === false" in frontend
    assert "detail.reason" in frontend
    assert "activeEffort" in frontend
    assert "if (activeEffort) return" in frontend
    assert "isActive && isOverride ? '' : lvl" not in frontend
    assert "Retirer l’override et réappliquer l’effort hérité" in frontend


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


def test_web_submit_sends_enter_once_without_capture_retry():
    """Chaque chemin exclusif valide une fois, sans retry via le scrollback."""
    agents = (ROOT / "web/backend/multi_agent/routers/agents.py").read_text()
    submit = agents.split("if data.submit:", 1)[1].split("else:", 1)[0]
    synced, atomic = submit.split("# Soumission atomique", 1)
    assert synced.count('"Enter"') == 1
    assert atomic.count('"Enter"') == 1
    assert '"capture-pane"' not in submit


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
    assert "await _collect_keepalive_profile(profile)" in start
    assert '"collection": "ok"' in start


def test_profile_snapshot_always_has_engine_session_and_scan(tmp_path, monkeypatch):
    scheduler = _load_scheduler()
    monkeypatch.setattr(scheduler, "KEEPALIVE_DIR", str(tmp_path))
    snapshot = scheduler._write_profile_snapshot(
        "codex1a", "agent-002-codex1a", [{"label": "Weekly", "percent": 2}], {
            "email": "user@example.com",
        }, "ok",
    )
    assert snapshot["source_session"] == "agent-002-codex1a"
    assert snapshot["info"]["engine"] == "codex"
    assert snapshot["info"]["collection_status"] == "ok"
    assert snapshot["info"]["source_session"] == "agent-002-codex1a"
    assert snapshot["last_scan"] > 0


def test_round_robin_uses_engine_aware_profile_collector():
    source = (ROOT / "scripts" / "crontab-scheduler.py").read_text()
    scan = source[source.index("def scan_keepalive()"):source.index("def _pane_text")]
    assert "_collect_profile_status(profile" in scan
    assert "_scrape_usage_tab(session)" not in scan


def test_probe_collects_live_profile_when_snapshot_is_missing():
    source = (ROOT / "web/backend/multi_agent/routers/config.py").read_text()
    probe = source[source.index("async def probe_keepalive"):]
    assert "if not info:" in probe
    assert '["tmux", "has-session", "-t", expected_session]' in probe
    assert "await _collect_keepalive_profile(profile)" in probe


def test_agent_usage_resolves_neutral_login_slot_to_engine_profile():
    source = (ROOT / "web/backend/multi_agent/routers/agents.py").read_text()
    usage = source[source.index("async def get_usage_for_agent"):source.index(
        "async def get_agent", source.index("async def get_usage_for_agent")
    )]
    assert 're.fullmatch(r"login\\d[a-z]", login)' in usage
    assert "engines.agent_engine(prompts_dir, agent_id)" in usage
    assert "login = f\"{engine}{login.removeprefix('login')}\"" in usage


def test_keepalive_compact_table_keeps_login_and_usage_status_fallback():
    source = (ROOT / "web/frontend/src/components/KeepAliveSplit.jsx").read_text()
    assert "<th>Login</th><th>État</th><th>Usage</th>" in source
    assert "ki?.email || ki?.login_method" in source
    assert ".slice(0, 15)" in source
    assert "ki?.collection_status || usage?.status || 'collecte…'" in source
    assert "ka-scan-age" not in source
    assert "shortLabel(" not in source
    css = (ROOT / "web/frontend/src/index.css").read_text()
    usage_bar = css[css.index(".lm-usage-bar {"):css.index("}", css.index(".lm-usage-bar {"))]
    assert "display: inline-block" in usage_bar


def test_agent_header_usage_has_only_profile_and_sliders():
    source = (ROOT / "web/frontend/src/components/terminal/UsageBars.jsx").read_text()
    assert '<span className="usage-bar-name">{usage.login}</span>' in source
    assert "usage-bar-track" in source
    assert "shortLabel(" not in source
    assert "usage-bar-short-label" not in source
    assert "apiFetch(`api/usage/${agentId}`" in source
    assert "agentId.slice(4)" in source


def test_wait_prompt_sees_claude_prompt_above_usage_credit_status(monkeypatch):
    scheduler = _load_scheduler()
    pane = '\n'.join([
        '────────────────',
        '❯\\u00a0Try "fix lint errors"',
        '────────────────',
        '  bypass permissions on',
        '  Now using usage credits',
    ])
    monkeypatch.setattr(scheduler, "_pane_text", lambda _session: pane)
    monkeypatch.setattr(scheduler, "_ready_markers", lambda _profile: ("❯",))
    monkeypatch.setattr(scheduler, "_login_expired_markers", lambda _profile: ())
    assert scheduler._wait_prompt(
        "agent-002-claude1a", timeout_s=0.1, profile="claude1a",
    ) == "ready"


def test_claude_usage_keeps_latest_duplicate_card(monkeypatch):
    scheduler = _load_scheduler()
    outputs = iter([
        "❯ ready",
        "Settings  Status  Config  Usage  Stats",
        "Settings:\nLogin method: Claude Max account\nModel: claude-opus-4-8",
        "\n".join([
            "Current week (all models)", "10% used",
            "Current week (all models)", "65% used",
        ]),
        """
Total cost: $0.0000
Total duration (API): 0s
Total duration (wall): 1m
Total code changes: 0 lines added, 0 lines removed
Usage: 0 input, 0 output, 0 cache read, 0 cache write
""",
    ])

    def fake_run(command, **_kwargs):
        if command[:2] == ["tmux", "capture-pane"]:
            return SimpleNamespace(returncode=0, stdout=next(outputs))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _seconds: None)
    bars, _info = scheduler._scrape_usage_tab("agent-002-claude1a")
    assert bars == [{
        "label": "Current week (all models)", "percent": 65, "resets": "",
    }]


def test_claude_runtime_banner_is_available_while_logged_out():
    scheduler = _load_scheduler()
    info = scheduler._parse_runtime_banner(
        """
Claude Code v2.1.220
▝▜█████▛▘  Fable 5 with xhigh effort · API Usage Billing
  ▘▘ ▝▝    ~/multi-agent
Not logged in · Run /login
""",
        "claude",
    )
    assert info == {
        "cli_version": "2.1.220",
        "model": "Fable 5",
        "effort": "xhigh",
        "billing": "API Usage Billing",
        "cwd": "~/multi-agent",
    }


def test_claude_session_stats_parser_covers_all_visible_fields():
    scheduler = _load_scheduler()
    assert scheduler._parse_claude_session_stats(
        """
Total cost:            $0.0000
Total duration (API):  2m 3s
Total duration (wall): 6m 2s
Total code changes:    12 lines added, 4 lines removed
Usage:                 123 input, 45 output, 67 cache read, 8 cache write
"""
    ) == {
        "total_cost": "$0.0000",
        "duration_api": "2m 3s",
        "duration_wall": "6m 2s",
        "lines_added": 12,
        "lines_removed": 4,
        "input_tokens": 123,
        "output_tokens": 45,
        "cache_read_tokens": 67,
        "cache_write_tokens": 8,
    }


def test_claude_scrape_anchors_tabs_and_collects_stats():
    source = (ROOT / "scripts/crontab-scheduler.py").read_text()
    scrape = source[source.index("def _scrape_usage_tab"):source.index(
        "def _write_profile_snapshot"
    )]
    assert '"Login method:", "Organization:", "Email:"' in scrape
    assert 'if "% used" in output:' in scrape
    assert 'if "Total cost:" in stats_output:' in scrape
    assert "_parse_claude_session_stats" in scrape


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
