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
