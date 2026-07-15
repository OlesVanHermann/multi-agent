"""Régressions v3.1.4 : keepalive Codex, défaut global et sandbox systemd."""

import importlib.util
import json
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
Weekly limit: [████] 79% left
              (resets 22:20 on 21 Jul)
GPT-5.3-Codex-Spark Weekly limit: [████] 100% left
"""
    monkeypatch.setattr(scheduler, "_pane_text", lambda _session: pane)
    monkeypatch.setattr(scheduler.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _seconds: None)
    bars, info = scheduler._scrape_codex_status("A-agent-002-codex1a")
    assert [b["percent"] for b in bars] == [21, 0]
    assert info["email"] == "user@example.com"
    assert info["login_method"] == "ChatGPT account"


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
