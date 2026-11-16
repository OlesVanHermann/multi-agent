"""Contrôles groupés des mono-pairs dans le panneau login/modèle."""

import asyncio
import json
from pathlib import Path

from web.backend.multi_agent import state
from web.backend.multi_agent.routers import agents as agents_router
from web.backend.multi_agent.routers import config as config_router


def _mono_tree(tmp_path: Path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "login1a.login").write_text("slot\n")
    (prompts / "fable-5.model").write_text("claude-fable-5\n")
    (prompts / "default.login").symlink_to("login1a.login")
    (prompts / "default.model").symlink_to("fable-5.model")
    mono = prompts / "300-example"
    mono.mkdir()
    (mono / "agent.type").symlink_to("../agent_mono.type")
    (mono / "mono-pair.json").write_text(json.dumps({
        "type": "mono-pair", "main": "300-100", "contradictor": "300-200",
    }))
    for member in ("300-100", "300-200"):
        (mono / f"{member}-system.md").write_text(member)
    return prompts


def test_mono_pair_is_exposed_as_group(tmp_path, monkeypatch):
    _mono_tree(tmp_path)
    monkeypatch.setattr(config_router.cfg, "BASE_DIR", tmp_path)
    monkeypatch.setattr(state, "_cache", {"agents": []})
    data = asyncio.run(config_router.get_logins_models())
    assert [a["id"] for a in data["agents"]] == ["300-100", "300-200"]
    assert data["groups"] == [{
        "id": "300", "type": "mono", "name": "300-example",
        "agents": ["300-100", "300-200"],
    }]


def test_lifecycle_verifies_real_mono_member_sessions(tmp_path, monkeypatch):
    _mono_tree(tmp_path)
    monkeypatch.setattr(agents_router.cfg, "BASE_DIR", tmp_path)
    assert agents_router._lifecycle_member_ids("300") == ["300-100", "300-200"]
    assert agents_router._lifecycle_member_ids("300-100") == ["300-100"]


def test_lifecycle_reports_each_member(tmp_path, monkeypatch):
    """Résumé x45/z21 du dashboard : état cible atteint membre par membre."""
    _mono_tree(tmp_path)
    monkeypatch.setattr(agents_router.cfg, "BASE_DIR", tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "agent.sh").write_text("#!/bin/bash\n")

    class _Result:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    async def fake_run(command, **kwargs):
        if command[:2] == ["tmux", "has-session"]:
            # 300-200 survit au stop : son état cible n'est pas atteint.
            return _Result(0 if command[-1].endswith("300-200") else 1)
        return _Result(0, "[OK] Done")

    async def no_sleep(_):
        return None

    monkeypatch.setattr(agents_router, "_run_subprocess", fake_run)
    monkeypatch.setattr(agents_router.asyncio, "sleep", no_sleep)
    result = asyncio.run(agents_router._agent_lifecycle("300", "stop"))
    assert result["verified"] is False
    assert result["member_ok"] == {"300-100": True, "300-200": False}
